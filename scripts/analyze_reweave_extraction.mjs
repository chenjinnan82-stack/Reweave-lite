import crypto from "node:crypto";
import path from "node:path";
import process from "node:process";
import * as ts from "typescript";

class Rejection extends Error {
  constructor(code, logicalPath = "") {
    super(code);
    this.code = code;
    this.logicalPath = logicalPath;
  }
}

const payload = JSON.parse(await new Promise((resolve) => {
  let data = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => { data += chunk; });
  process.stdin.on("end", () => resolve(data));
}));

const entryModules = Array.isArray(payload.entry_modules) ? payload.entry_modules.map(String) : [];
const moduleSnapshot = Array.isArray(payload.module_snapshot) ? payload.module_snapshot : [];
const htmlSelectors = new Set(Array.isArray(payload.html_selectors) ? payload.html_selectors.map(String) : []);
const htmlControls = payload.html_controls && typeof payload.html_controls === "object" ? payload.html_controls : {};
const snapshotModules = new Map();
const moduleCache = new Map();
const casePaths = new Map();
const forbiddenContractNames = new Set(["__proto__", "prototype", "constructor"]);
const MAX_LITERAL_VALUE_LENGTH = 10_000;
const MAX_LITERAL_VALUE_COUNT = 256;
const MAX_LITERAL_EVIDENCE_BYTES = 64 * 1024;
const MAX_STATIC_STRING_DEPTH = 32;
const MAX_STATIC_STRING_STEPS = 4096;
const ignoredModuleSegments = new Set([
  ".git",
  ".next",
  ".turbo",
  ".venv",
  "__pycache__",
  "build",
  "dist",
  "node_modules",
  "target",
  "vendor",
  "venv",
]);
const forbiddenStringFunctions = new Set([
  "JSON",
  "String",
  "atob",
  "btoa",
  "decodeURI",
  "decodeURIComponent",
  "encodeURI",
  "encodeURIComponent",
]);
const forbiddenStringMethods = new Set([
  "at",
  "charAt",
  "concat",
  "join",
  "normalize",
  "padEnd",
  "padStart",
  "parse",
  "repeat",
  "replace",
  "replaceAll",
  "slice",
  "substr",
  "substring",
  "toLocaleLowerCase",
  "toLocaleUpperCase",
  "toLowerCase",
  "toString",
  "toUpperCase",
  "trim",
  "trimEnd",
  "trimStart",
  "stringify",
]);

function normalizeRel(value) {
  const raw = String(value || "");
  if (!raw || raw.includes("\\") || path.posix.isAbsolute(raw)) throw new Rejection("module_path_invalid");
  const normalized = path.posix.normalize(raw);
  if (normalized === "." || normalized === ".." || normalized.startsWith("../") || normalized.split("/").includes(".")) {
    throw new Rejection("module_path_outside_project", raw);
  }
  return normalized;
}

function hasIgnoredModuleSegment(relative) {
  return relative.split("/").some((part) => {
    const folded = part.toLocaleLowerCase("en-US");
    return ignoredModuleSegments.has(folded) || folded.startsWith(".venv");
  });
}

function safeModulePath(relative) {
  const rel = normalizeRel(relative);
  if (!/[.](?:js|mjs)$/.test(rel)) throw new Rejection("module_extension_unsupported", rel);
  if (hasIgnoredModuleSegment(rel)) throw new Rejection("module_path_excluded", rel);
  const snapshot = snapshotModules.get(rel);
  if (!snapshot) throw new Rejection("module_not_found", rel);
  const folded = rel.toLocaleLowerCase("en-US");
  const previous = casePaths.get(folded);
  if (previous && previous !== rel) throw new Rejection("module_case_conflict", rel);
  casePaths.set(folded, rel);
  return { rel, source: snapshot.source };
}

function initializeModuleSnapshot() {
  for (const item of moduleSnapshot) {
    if (!item || typeof item !== "object") throw new Rejection("module_snapshot_invalid");
    const rel = normalizeRel(item.path);
    if (!/[.](?:js|mjs)$/.test(rel)) throw new Rejection("module_extension_unsupported", rel);
    if (hasIgnoredModuleSegment(rel)) throw new Rejection("module_path_excluded", rel);
    if (snapshotModules.has(rel)) throw new Rejection("module_snapshot_duplicate", rel);
    const folded = rel.toLocaleLowerCase("en-US");
    const previous = casePaths.get(folded);
    if (previous && previous !== rel) throw new Rejection("module_case_conflict", rel);
    const source = typeof item.source === "string" ? item.source : null;
    const digest = typeof item.sha256 === "string" ? item.sha256 : "";
    if (source === null || !/^[0-9a-f]{64}$/.test(digest)) throw new Rejection("module_snapshot_invalid", rel);
    const actual = crypto.createHash("sha256").update(source, "utf8").digest("hex");
    if (actual !== digest) throw new Rejection("module_snapshot_hash_mismatch", rel);
    snapshotModules.set(rel, { source, sha256: digest });
    casePaths.set(folded, rel);
  }
  casePaths.clear();
}

function importTarget(from, specifier) {
  if (!specifier.startsWith("./") && !specifier.startsWith("../")) throw new Rejection("module_bare_specifier", from);
  if (/^(?:https?:|data:|blob:)/i.test(specifier)) throw new Rejection("module_remote_specifier", from);
  return normalizeRel(path.posix.join(path.posix.dirname(from), specifier));
}

function hasModifier(node, kind) {
  return Boolean(node.modifiers?.some((item) => item.kind === kind));
}

function containsTopLevelEffect(node) {
  if (ts.isFunctionLike(node)) return false;
  let effect = false;
  function visit(current) {
    if (effect) return;
    if (
      ts.isCallExpression(current)
      || ts.isNewExpression(current)
      || ts.isAwaitExpression(current)
      || ts.isYieldExpression(current)
      || ts.isDeleteExpression(current)
      || ts.isPostfixUnaryExpression(current)
      || (ts.isPrefixUnaryExpression(current) && [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(current.operator))
      || (ts.isBinaryExpression(current) && current.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && current.operatorToken.kind <= ts.SyntaxKind.LastAssignment)
    ) {
      effect = true;
      return;
    }
    ts.forEachChild(current, visit);
  }
  visit(node);
  return effect;
}

function loadModule(relative) {
  const { rel, source } = safeModulePath(relative);
  if (moduleCache.has(rel)) return moduleCache.get(rel);
  if (Buffer.byteLength(source, "utf8") > 1024 * 1024) throw new Rejection("module_too_large", rel);
  const tree = ts.createSourceFile(rel, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  if (tree.parseDiagnostics.length) throw new Rejection("module_syntax_invalid", rel);
  const imports = [];
  const importBindings = new Map();
  const functions = new Map();
  const exports = new Map();
  const symbols = new Map();
  for (const statement of tree.statements) {
    if (ts.isImportDeclaration(statement)) {
      if (!statement.importClause || !ts.isStringLiteral(statement.moduleSpecifier) || statement.assertClause || statement.attributes) {
        throw new Rejection("module_import_unsupported", rel);
      }
      const target = importTarget(rel, statement.moduleSpecifier.text);
      imports.push(target);
      const clause = statement.importClause;
      if (clause.name) importBindings.set(clause.name.text, { target, imported: "default" });
      if (clause.namedBindings) {
        if (!ts.isNamedImports(clause.namedBindings)) throw new Rejection("module_import_unsupported", rel);
        for (const item of clause.namedBindings.elements) {
          importBindings.set(item.name.text, { target, imported: item.propertyName?.text || item.name.text });
        }
      }
      continue;
    }
    if (ts.isExportDeclaration(statement)) {
      if (statement.moduleSpecifier || !statement.exportClause || !ts.isNamedExports(statement.exportClause)) {
        throw new Rejection("module_reexport_forbidden", rel);
      }
      for (const item of statement.exportClause.elements) {
        exports.set(item.name.text, item.propertyName?.text || item.name.text);
      }
      continue;
    }
    if (ts.isExportAssignment(statement)) {
      if (ts.isArrowFunction(statement.expression) || ts.isFunctionExpression(statement.expression)) {
        throw new Rejection("anonymous_default_export_unsupported_v1", rel);
      }
      if (statement.isExportEquals || !ts.isIdentifier(statement.expression)) {
        throw new Rejection("module_export_unsupported", rel);
      }
      exports.set("default", statement.expression.text);
      continue;
    }
    if (ts.isFunctionDeclaration(statement)
        && hasModifier(statement, ts.SyntaxKind.DefaultKeyword)
        && !statement.name) {
      throw new Rejection("anonymous_default_export_unsupported_v1", rel);
    }
    if (ts.isFunctionDeclaration(statement) && statement.name && statement.body) {
      if (symbols.has(statement.name.text)) throw new Rejection("module_symbol_duplicate", rel);
      functions.set(statement.name.text, statement);
      symbols.set(statement.name.text, statement);
      if (hasModifier(statement, ts.SyntaxKind.ExportKeyword)) {
        exports.set(hasModifier(statement, ts.SyntaxKind.DefaultKeyword) ? "default" : statement.name.text, statement.name.text);
      }
      continue;
    }
    if (ts.isVariableStatement(statement)) {
      if ((statement.declarationList.flags & ts.NodeFlags.Const) === 0) throw new Rejection("module_top_level_mutable_state", rel);
      for (const declaration of statement.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || !declaration.initializer || containsTopLevelEffect(declaration.initializer)) {
          throw new Rejection("module_top_level_side_effect", rel);
        }
        if (symbols.has(declaration.name.text)) throw new Rejection("module_symbol_duplicate", rel);
        symbols.set(declaration.name.text, declaration.initializer);
        if (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer)) {
          functions.set(declaration.name.text, declaration.initializer);
          if (hasModifier(statement, ts.SyntaxKind.ExportKeyword)) exports.set(declaration.name.text, declaration.name.text);
        }
      }
      continue;
    }
    if (!ts.isEmptyStatement(statement)) throw new Rejection("module_top_level_statement_unsupported", rel);
  }
  let dynamic = false;
  function inspect(current, functionDepth = 0) {
    if (ts.isCallExpression(current) && (current.expression.kind === ts.SyntaxKind.ImportKeyword || (ts.isIdentifier(current.expression) && current.expression.text === "require"))) dynamic = true;
    if (ts.isAwaitExpression(current) && functionDepth === 0) dynamic = true;
    const nextDepth = ts.isFunctionLike(current) ? functionDepth + 1 : functionDepth;
    ts.forEachChild(current, (child) => inspect(child, nextDepth));
  }
  inspect(tree);
  if (dynamic) throw new Rejection("module_dynamic_execution_unsupported", rel);
  const record = { rel, source, tree, imports, importBindings, functions, exports, symbols };
  moduleCache.set(rel, record);
  return record;
}

function moduleClosure(entry) {
  const ordered = [];
  const visiting = new Set();
  const visited = new Set();
  function visit(relative, depth) {
    if (depth > 8) throw new Rejection("module_depth_exceeded", relative);
    const record = loadModule(relative);
    if (visiting.has(record.rel)) throw new Rejection("module_cycle", record.rel);
    if (visited.has(record.rel)) return;
    visiting.add(record.rel);
    for (const dependency of record.imports) visit(dependency, depth + 1);
    visiting.delete(record.rel);
    visited.add(record.rel);
    ordered.push(record.rel);
    if (ordered.length > 32) throw new Rejection("module_count_exceeded", record.rel);
  }
  visit(entry, 0);
  return ordered.sort();
}

function isDeclarationName(node) {
  const parent = node.parent;
  return Boolean(
    (ts.isFunctionDeclaration(parent) && parent.name === node)
    || (ts.isFunctionExpression(parent) && parent.name === node)
    || (ts.isParameter(parent) && parent.name === node)
    || (ts.isVariableDeclaration(parent) && parent.name === node)
    || (ts.isBindingElement(parent) && parent.name === node)
    || (ts.isClassDeclaration(parent) && parent.name === node)
  );
}

function isSymbolReference(node) {
  const parent = node.parent;
  if (isDeclarationName(node)) return false;
  if (ts.isPropertyAccessExpression(parent) && parent.name === node) return false;
  if (ts.isPropertyAssignment(parent) && parent.name === node) return false;
  if (ts.isMethodDeclaration(parent) && parent.name === node) return false;
  if (ts.isPropertyDeclaration(parent) && parent.name === node) return false;
  if (ts.isImportSpecifier(parent) || ts.isExportSpecifier(parent)) return false;
  if (ts.isLabeledStatement(parent) || ts.isBreakOrContinueStatement(parent)) return false;
  return true;
}

function statementBinding(statements, name) {
  for (const statement of statements) {
    if (ts.isFunctionDeclaration(statement) && statement.name?.text === name) {
      return { initializer: null };
    }
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || declaration.name.text !== name) continue;
      const immutable = (statement.declarationList.flags & ts.NodeFlags.Const) !== 0;
      return {
        initializer: immutable
          && declaration.initializer
          && !ts.isFunctionLike(declaration.initializer)
          ? declaration.initializer
          : null,
      };
    }
  }
  return null;
}

function declarationListBinding(declarationList, name) {
  if (!declarationList || !ts.isVariableDeclarationList(declarationList)) return null;
  for (const declaration of declarationList.declarations) {
    if (!ts.isIdentifier(declaration.name) || declaration.name.text !== name) continue;
    const immutable = (declarationList.flags & ts.NodeFlags.Const) !== 0;
    return {
      initializer: immutable
        && declaration.initializer
        && !ts.isFunctionLike(declaration.initializer)
        ? declaration.initializer
        : null,
    };
  }
  return null;
}

function immutableConstInitializer(identifier) {
  const name = identifier.text;
  let current = identifier.parent;
  while (current) {
    if (ts.isBlock(current)) {
      const binding = statementBinding(current.statements, name);
      if (binding) return binding.initializer;
    }
    if (ts.isForStatement(current)) {
      const binding = declarationListBinding(current.initializer, name);
      if (binding) return binding.initializer;
    }
    if (ts.isForInStatement(current) || ts.isForOfStatement(current)) {
      const binding = declarationListBinding(current.initializer, name);
      if (binding) return binding.initializer;
    }
    if (ts.isCatchClause(current)
        && current.variableDeclaration
        && ts.isVariableDeclaration(current.variableDeclaration)
        && ts.isIdentifier(current.variableDeclaration.name)
        && current.variableDeclaration.name.text === name) {
      return null;
    }
    if (ts.isFunctionLike(current)) {
      if (current.parameters.some((item) => ts.isIdentifier(item.name) && item.name.text === name)) {
        return null;
      }
      if ((ts.isFunctionDeclaration(current) || ts.isFunctionExpression(current))
          && current.name?.text === name) {
        return null;
      }
    }
    if (ts.isSourceFile(current)) {
      const record = moduleCache.get(current.fileName);
      const symbol = record?.symbols.get(name);
      if (symbol) return ts.isFunctionLike(symbol) ? null : symbol;
      const binding = record?.importBindings.get(name);
      const target = binding ? moduleCache.get(binding.target) : null;
      const local = target?.exports.get(binding?.imported);
      const imported = local ? target?.symbols.get(local) : null;
      return imported && !ts.isFunctionLike(imported) ? imported : null;
    }
    current = current.parent;
  }
  return null;
}

function staticComposedString(node, state, depth = 0) {
  if (state.cache.has(node)) return state.cache.get(node);
  if (depth > MAX_STATIC_STRING_DEPTH || state.steps >= MAX_STATIC_STRING_STEPS) {
    throw new Rejection("literal_evidence_budget_exceeded_v1");
  }
  if (state.active.has(node)) throw new Rejection("unsupported_extraction_boundary_v1");
  state.steps += 1;
  state.active.add(node);
  let result = null;
  try {
    if (ts.isParenthesizedExpression(node)) {
      result = staticComposedString(node.expression, state, depth + 1);
    } else if (ts.isStringLiteralLike(node)) {
      result = { value: node.text, parts: 1 };
    } else if (ts.isIdentifier(node)) {
      const initializer = immutableConstInitializer(node);
      if (initializer) result = staticComposedString(initializer, state, depth + 1);
    } else if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const left = staticComposedString(node.left, state, depth + 1);
      const right = staticComposedString(node.right, state, depth + 1);
      if (left && right) {
        if (left.value.length + right.value.length > MAX_LITERAL_VALUE_LENGTH) {
          throw new Rejection("literal_evidence_budget_exceeded_v1");
        }
        result = { value: left.value + right.value, parts: left.parts + right.parts };
      }
    } else if (ts.isTemplateExpression(node)) {
      let value = node.head.text;
      if (value.length > MAX_LITERAL_VALUE_LENGTH) throw new Rejection("literal_evidence_budget_exceeded_v1");
      let parts = 1;
      for (const span of node.templateSpans) {
        const expression = staticComposedString(span.expression, state, depth + 1);
        if (!expression) {
          value = null;
          break;
        }
        if (value.length + expression.value.length + span.literal.text.length > MAX_LITERAL_VALUE_LENGTH) {
          throw new Rejection("literal_evidence_budget_exceeded_v1");
        }
        value += expression.value + span.literal.text;
        parts += expression.parts + 1;
      }
      if (value !== null) result = { value, parts };
    }
  } finally {
    state.active.delete(node);
  }
  state.cache.set(node, result);
  return result;
}

function boundedLiteralEvidence(literalValues, composedLiteralValues) {
  const literals = [...literalValues].sort();
  const composed = [...composedLiteralValues].sort();
  if (literals.length > MAX_LITERAL_VALUE_COUNT || composed.length > MAX_LITERAL_VALUE_COUNT) {
    throw new Rejection("literal_evidence_budget_exceeded_v1");
  }
  if (literals.some((item) => item.length > MAX_LITERAL_VALUE_LENGTH)
      || composed.some((item) => item.length > MAX_LITERAL_VALUE_LENGTH)
      || Buffer.byteLength(JSON.stringify({ literals, composed }), "utf8") > MAX_LITERAL_EVIDENCE_BYTES) {
    throw new Rejection("literal_evidence_budget_exceeded_v1");
  }
  return { literalValues: literals, composedLiteralValues: composed };
}

function isUnresolvedStringConstruction(node, composed, capabilityKind) {
  if (composed) return false;
  if (ts.isTemplateExpression(node)) return true;
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    const state = { cache: new WeakMap(), active: new Set(), steps: 0 };
    const left = staticComposedString(node.left, state);
    const right = staticComposedString(node.right, state);
    return Boolean(left || right || capabilityKind !== "computation");
  }
  return false;
}

function staticMemberName(node) {
  if (ts.isPropertyAccessExpression(node)) return node.name.text;
  if (ts.isElementAccessExpression(node)) {
    const value = staticComposedString(node.argumentExpression, {
      cache: new WeakMap(),
      active: new Set(),
      steps: 0,
    });
    return value?.value || null;
  }
  return null;
}

function isExecutableMemberValue(node) {
  let current = node;
  while (ts.isParenthesizedExpression(current.parent)) current = current.parent;
  const parent = current.parent;
  return Boolean(
    (ts.isCallExpression(parent) && parent.expression === current)
    || (ts.isVariableDeclaration(parent) && parent.initializer === current)
  );
}

function isForbiddenStringReference(node) {
  if (ts.isIdentifier(node)
      && isSymbolReference(node)
      && forbiddenStringFunctions.has(node.text)) {
    return true;
  }
  if (!ts.isPropertyAccessExpression(node) && !ts.isElementAccessExpression(node)) return false;
  const member = staticMemberName(node);
  const owner = node.expression;
  if (ts.isIdentifier(owner)
      && owner.text === "JSON"
      && ["parse", "stringify"].includes(member)) {
    return true;
  }
  return (
    ts.isIdentifier(owner)
      && owner.text === "String"
      && ["fromCharCode", "fromCodePoint", "raw"].includes(member)
  ) || Boolean(member && forbiddenStringMethods.has(member) && isExecutableMemberValue(node));
}

function assertAtomicSymbolClosure(entryRecord, entrySymbol, modules, capabilityKind) {
  const reachable = new Set();
  const literalValues = new Set();
  const composedLiteralValues = new Set();
  const composedState = {
    cache: new WeakMap(),
    active: new Set(),
    steps: 0,
  };
  const pending = [{ record: entryRecord, symbol: entrySymbol }];
  while (pending.length) {
    const { record, symbol } = pending.pop();
    const key = `${record.rel}:${symbol}`;
    if (reachable.has(key)) continue;
    const root = record.symbols.get(symbol);
    if (!root) throw new Rejection("unsupported_extraction_boundary_v1", record.rel);
    reachable.add(key);
    const names = new Set([...record.symbols.keys(), ...record.importBindings.keys()]);
    function visit(current) {
      if (ts.isStringLiteralLike(current)) literalValues.add(current.text);
      if (isForbiddenStringReference(current)) {
        throw new Rejection("unsupported_string_construction_v1", record.rel);
      }
      if (ts.isBinaryExpression(current) || ts.isTemplateExpression(current)) {
        const composed = staticComposedString(current, composedState);
        if (isUnresolvedStringConstruction(current, composed, capabilityKind)) {
          throw new Rejection("unsupported_string_construction_v1", record.rel);
        }
        if (composed?.parts > 1) {
          literalValues.add(composed.value);
          composedLiteralValues.add(composed.value);
        }
      }
      if (ts.isIdentifier(current) && names.has(current.text)) {
        if (isDeclarationName(current)) {
          const isRootName = (ts.isFunctionDeclaration(root) || ts.isFunctionExpression(root))
            && root.name === current;
          if (!isRootName) throw new Rejection("unsupported_extraction_boundary_v1", record.rel);
        } else if (isSymbolReference(current)) {
          if (record.symbols.has(current.text)) {
            pending.push({ record, symbol: current.text });
          } else {
            const binding = record.importBindings.get(current.text);
            const target = moduleCache.get(binding.target);
            const local = target?.exports.get(binding.imported);
            if (!local || !target.symbols.has(local)) {
              throw new Rejection("unsupported_extraction_boundary_v1", binding.target);
            }
            pending.push({ record: target, symbol: local });
          }
        }
      }
      ts.forEachChild(current, visit);
    }
    visit(root);
  }
  for (const relative of modules) {
    const record = moduleCache.get(relative);
    for (const symbol of record.symbols.keys()) {
      if (!reachable.has(`${relative}:${symbol}`)) {
        throw new Rejection("unsupported_extraction_boundary_v1", relative);
      }
    }
  }
  return boundedLiteralEvidence(literalValues, composedLiteralValues);
}

function assertCandidateSymbolCoverage(entryRecord, entrySymbol, modules, candidate) {
  const covered = new Set([`${entryRecord.rel}:${entrySymbol}`]);
  for (const dependency of candidate.dependencies) {
    if (dependency.type === "static_call") {
      covered.add(`${dependency.to_module}:${dependency.to_symbol}`);
    }
  }
  for (const relative of modules) {
    const record = moduleCache.get(relative);
    for (const symbol of record.symbols.keys()) {
      if (!record.functions.has(symbol) || !covered.has(`${relative}:${symbol}`)) {
        throw new Rejection("unsupported_extraction_boundary_v1", relative);
      }
    }
  }
}

function staticString(node) {
  return node && ts.isStringLiteralLike(node) ? node.text : null;
}

function checkedContractName(value, code) {
  if (!value || forbiddenContractNames.has(value)) throw new Rejection(code);
  return value;
}

function propertyPath(node) {
  const parts = [];
  let current = node;
  while (ts.isPropertyAccessExpression(current)) {
    parts.unshift(current.name.text);
    current = current.expression;
  }
  if (!ts.isIdentifier(current)) return null;
  parts.unshift(current.text);
  return parts;
}

function fieldName(node, base) {
  const parts = propertyPath(node);
  if (!parts || parts.length !== base.length + 1 || !base.every((item, index) => parts[index] === item)) return null;
  return checkedContractName(parts.at(-1), "contract_member_forbidden_v1");
}

function objectProperty(node, name) {
  if (!node || !ts.isObjectLiteralExpression(node)) return null;
  for (const item of node.properties) {
    if (!ts.isPropertyAssignment(item)) continue;
    const key = ts.isIdentifier(item.name) || ts.isStringLiteralLike(item.name) ? item.name.text : "";
    if (key === name) return item.initializer;
  }
  return null;
}

function closedObjectProperties(node, allowed, required, code) {
  if (!node || !ts.isObjectLiteralExpression(node)) throw new Rejection(code);
  const properties = new Map();
  for (const item of node.properties) {
    if (!ts.isPropertyAssignment(item)
        || !(ts.isIdentifier(item.name) || ts.isStringLiteralLike(item.name))
        || !allowed.has(item.name.text)
        || properties.has(item.name.text)) {
      throw new Rejection(code);
    }
    properties.set(item.name.text, item.initializer);
  }
  if ([...required].some((name) => !properties.has(name))) throw new Rejection(code);
  return properties;
}

function errorResult(node) {
  if (!node || !ts.isObjectLiteralExpression(node)) return null;
  const ok = objectProperty(node, "ok");
  if (ok?.kind !== ts.SyntaxKind.FalseKeyword) return null;
  const result = closedObjectProperties(
    node,
    new Set(["ok", "error"]),
    new Set(["ok", "error"]),
    "error_contract_unsupported_v1",
  );
  const error = closedObjectProperties(
    result.get("error"),
    new Set(["code", "field", "details"]),
    new Set(["code"]),
    "error_contract_unsupported_v1",
  );
  const code = checkedContractName(staticString(error.get("code")), "error_contract_unsupported_v1");
  const fieldNode = error.get("field");
  let field = null;
  if (fieldNode && fieldNode.kind !== ts.SyntaxKind.NullKeyword) {
    field = checkedContractName(staticString(fieldNode), "error_contract_unsupported_v1");
  }
  const details = error.get("details");
  if (details && !ts.isObjectLiteralExpression(details)) throw new Rejection("error_contract_unsupported_v1");
  return { code, field, details };
}

function returnedStatement(statement) {
  if (ts.isReturnStatement(statement)) return statement;
  if (!ts.isBlock(statement)) return null;
  const rows = statement.statements.filter((item) => ts.isReturnStatement(item));
  return rows.length === 1 ? rows[0] : null;
}

function flattenOr(node, result = []) {
  if (ts.isParenthesizedExpression(node)) return flattenOr(node.expression, result);
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.BarBarToken) {
    flattenOr(node.left, result);
    flattenOr(node.right, result);
  } else {
    result.push(node);
  }
  return result;
}

function numericLiteral(node) {
  if (ts.isNumericLiteral(node)) return Number(node.text);
  if (ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.MinusToken && ts.isNumericLiteral(node.operand)) return -Number(node.operand.text);
  return null;
}

function applyGuard(atom, base, constraints) {
  if (ts.isPrefixUnaryExpression(atom) && atom.operator === ts.SyntaxKind.ExclamationToken && ts.isCallExpression(atom.operand)) {
    const call = atom.operand;
    if (ts.isPropertyAccessExpression(call.expression) && ts.isIdentifier(call.expression.expression) && call.expression.expression.text === "Number" && call.expression.name.text === "isInteger") {
      const name = fieldName(call.arguments[0], base);
      if (name) constraints.set(name, { ...(constraints.get(name) || {}), type: "integer" });
    }
    return;
  }
  if (!ts.isBinaryExpression(atom)) return;
  const operator = atom.operatorToken.kind;
  if ([ts.SyntaxKind.ExclamationEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken].includes(operator)) {
    let typeNode = null;
    let valueNode = null;
    if (ts.isTypeOfExpression(atom.left)) { typeNode = atom.left.expression; valueNode = atom.right; }
    if (ts.isTypeOfExpression(atom.right)) { typeNode = atom.right.expression; valueNode = atom.left; }
    const name = typeNode ? fieldName(typeNode, base) : null;
    const value = staticString(valueNode);
    if (name && ["string", "boolean"].includes(value)) constraints.set(name, { ...(constraints.get(name) || {}), type: value });
    return;
  }
  const comparisons = new Set([
    ts.SyntaxKind.LessThanToken,
    ts.SyntaxKind.LessThanEqualsToken,
    ts.SyntaxKind.GreaterThanToken,
    ts.SyntaxKind.GreaterThanEqualsToken,
  ]);
  if (!comparisons.has(operator)) return;
  let fieldNode = atom.left;
  let valueNode = atom.right;
  let op = operator;
  if (numericLiteral(valueNode) === null && numericLiteral(fieldNode) !== null) {
    fieldNode = atom.right;
    valueNode = atom.left;
    const reverse = new Map([
      [ts.SyntaxKind.LessThanToken, ts.SyntaxKind.GreaterThanToken],
      [ts.SyntaxKind.LessThanEqualsToken, ts.SyntaxKind.GreaterThanEqualsToken],
      [ts.SyntaxKind.GreaterThanToken, ts.SyntaxKind.LessThanToken],
      [ts.SyntaxKind.GreaterThanEqualsToken, ts.SyntaxKind.LessThanEqualsToken],
    ]);
    op = reverse.get(op);
  }
  const value = numericLiteral(valueNode);
  if (value === null || !Number.isSafeInteger(value)) return;
  let length = false;
  if (ts.isPropertyAccessExpression(fieldNode) && fieldNode.name.text === "length") {
    length = true;
    fieldNode = fieldNode.expression;
  }
  const name = fieldName(fieldNode, base);
  if (!name) return;
  const item = { ...(constraints.get(name) || {}) };
  if (length) item.length = true;
  if (op === ts.SyntaxKind.LessThanToken) item.minimum = value;
  if (op === ts.SyntaxKind.LessThanEqualsToken) item.minimum = value + 1;
  if (op === ts.SyntaxKind.GreaterThanToken) item.maximum = value;
  if (op === ts.SyntaxKind.GreaterThanEqualsToken) item.maximum = value - 1;
  constraints.set(name, item);
}

function rootObjectGuardCount(expression, base) {
  let stage = 0;
  let rejectsWrongKeyCount = null;
  for (let atom of flattenOr(expression)) {
    while (ts.isParenthesizedExpression(atom)) atom = atom.expression;
    if (ts.isPrefixUnaryExpression(atom)
        && atom.operator === ts.SyntaxKind.ExclamationToken
        && samePath(atom.operand, base)
        && stage === 0) {
      stage = 1;
      continue;
    }
    if (ts.isBinaryExpression(atom)
        && atom.operatorToken.kind === ts.SyntaxKind.ExclamationEqualsEqualsToken
        && ts.isTypeOfExpression(atom.left)
        && samePath(atom.left.expression, base)
        && staticString(atom.right) === "object"
        && stage === 1) {
      stage = 2;
      continue;
    }
    if (ts.isBinaryExpression(atom)
        && atom.operatorToken.kind === ts.SyntaxKind.ExclamationEqualsEqualsToken
        && ts.isPropertyAccessExpression(atom.left)
        && atom.left.name.text === "length"
        && ts.isCallExpression(atom.left.expression)
        && ts.isPropertyAccessExpression(atom.left.expression.expression)
        && ts.isIdentifier(atom.left.expression.expression.expression)
        && atom.left.expression.expression.expression.text === "Object"
        && atom.left.expression.expression.name.text === "keys"
        && atom.left.expression.arguments.length === 1
        && samePath(atom.left.expression.arguments[0], base)
        && stage === 2) {
      const count = numericLiteral(atom.right);
      if (!Number.isSafeInteger(count) || count < 0) return null;
      rejectsWrongKeyCount = count;
      stage = 3;
      continue;
    }
    return null;
  }
  return stage === 3 && Number.isSafeInteger(rejectsWrongKeyCount)
    ? rejectsWrongKeyCount
    : null;
}

function samePath(node, expected) {
  const parts = propertyPath(node);
  return Boolean(parts
    && parts.length === expected.length
    && expected.every((item, index) => parts[index] === item));
}

function inputContract(fn, base, capabilityKind) {
  const accessed = new Set();
  const constraints = new Map();
  const errors = new Map();
  const handledErrors = new Set();
  const returnedErrors = new Set();
  function scanAccess(current) {
    if (ts.isElementAccessExpression(current)) {
      const parts = propertyPath(current.expression);
      if (parts && parts.length === base.length && base.every((item, index) => parts[index] === item)) throw new Rejection("dynamic_input_field");
    }
    const name = fieldName(current, base);
    if (name) accessed.add(name);
    ts.forEachChild(current, scanAccess);
  }
  scanAccess(fn.body);
  function scanErrorReturns(current) {
    if (current !== fn.body && ts.isFunctionLike(current)) return;
    if (ts.isReturnStatement(current)) {
      if (!current.expression) {
        if (capabilityKind === "computation") throw new Rejection("error_contract_unsupported_v1");
      } else if (ts.isObjectLiteralExpression(current.expression)
          && objectProperty(current.expression, "ok")?.kind === ts.SyntaxKind.FalseKeyword) {
        returnedErrors.add(current);
      } else if (capabilityKind === "computation"
          && (!ts.isObjectLiteralExpression(current.expression)
            || objectProperty(current.expression, "ok")?.kind !== ts.SyntaxKind.TrueKeyword)) {
        throw new Rejection("error_contract_unsupported_v1");
      } else if (capabilityKind === "presentation") {
        throw new Rejection("error_contract_unsupported_v1");
      }
    }
    ts.forEachChild(current, scanErrorReturns);
  }
  scanErrorReturns(fn.body);
  for (const statement of fn.body.statements || []) {
    if (!ts.isIfStatement(statement)) continue;
    const returned = returnedStatement(statement.thenStatement);
    const error = errorResult(returned?.expression);
    if (!error) continue;
    const guarded = new Map();
    for (const atom of flattenOr(statement.expression)) applyGuard(atom, base, guarded);
    const fields = [...guarded.keys()];
    const rootCount = fields.length ? null : rootObjectGuardCount(statement.expression, base);
    if ((!fields.length && rootCount === null)
        || (rootCount !== null && error.field !== null)
        || (error.field !== null && (fields.length !== 1 || error.field !== fields[0]))) {
      throw new Rejection("error_contract_unsupported_v1");
    }
    for (const [name, value] of guarded) {
      if (constraints.has(name) && !sameContract(constraints.get(name), value)) {
        throw new Rejection("ambiguous_data_contract_v1");
      }
      constraints.set(name, value);
    }
    const details = error.details
      ? inferExpression(error.details, {
        modulePath: "",
        env: new Map(),
        locals: new Map(),
        propertyContracts: new Map(),
        dependencies: new Map(),
      })
      : { type: "object", properties: Object.create(null), required: [], additional_properties: false };
    if (details.type !== "object") throw new Rejection("error_contract_unsupported_v1");
    const row = {
      field: error.field,
      details: { schema: "data_contract.v1", ...details },
      rootCount,
    };
    if (errors.has(error.code) && !sameContract(errors.get(error.code), row)) {
      throw new Rejection("error_contract_unsupported_v1");
    }
    errors.set(error.code, row);
    handledErrors.add(returned);
  }
  if ([...returnedErrors].some((item) => !handledErrors.has(item))) {
    throw new Rejection("error_contract_unsupported_v1");
  }
  const properties = Object.create(null);
  for (const name of [...accessed].sort()) {
    const item = constraints.get(name) || {};
    if (item.type === "integer" && Number.isSafeInteger(item.minimum) && Number.isSafeInteger(item.maximum) && item.minimum <= item.maximum) {
      properties[name] = { type: "integer", minimum: item.minimum, maximum: item.maximum };
    } else if (item.type === "string" && item.length === true && Number.isSafeInteger(item.maximum) && (item.minimum || 0) <= item.maximum) {
      properties[name] = { type: "string", min_length: item.minimum || 0, max_length: item.maximum };
    } else if (item.type === "boolean") {
      properties[name] = { type: "boolean" };
    } else {
      throw new Rejection("ambiguous_data_contract_v1");
    }
  }
  const errorRows = Object.create(null);
  for (const [code, row] of [...errors].sort()) {
    if (row.rootCount !== null && row.rootCount !== Object.keys(properties).length) {
      throw new Rejection("error_contract_unsupported_v1");
    }
    errorRows[code] = { field: row.field, details: row.details };
  }
  return {
    contract: { schema: "data_contract.v1", type: "object", properties, required: Object.keys(properties).sort(), additional_properties: false },
    errorContract: { schema: "error_contract.v1", errors: errorRows },
  };
}

function localExpressions(fn) {
  const result = new Map();
  for (const statement of fn.body.statements || []) {
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (ts.isIdentifier(declaration.name) && declaration.initializer) result.set(declaration.name.text, declaration.initializer);
    }
  }
  return result;
}

function resolveFunction(modulePath, name) {
  const record = moduleCache.get(modulePath);
  if (!record) return null;
  if (record.functions.has(name)) return { modulePath, name, node: record.functions.get(name) };
  const binding = record.importBindings.get(name);
  if (!binding) return null;
  const target = moduleCache.get(binding.target);
  const local = target?.exports.get(binding.imported);
  return local ? { modulePath: binding.target, name: local, node: target.functions.get(local) } : null;
}

function sameContract(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function inferExpression(node, context, stack = new Set()) {
  if (!node) throw new Rejection("ambiguous_data_contract_v1");
  if (ts.isParenthesizedExpression(node)) return inferExpression(node.expression, context, stack);
  const staticValue = staticComposedString(node, {
    cache: new WeakMap(),
    active: new Set(),
    steps: 0,
  });
  if (staticValue) {
    return {
      type: "string",
      min_length: staticValue.value.length,
      max_length: staticValue.value.length,
    };
  }
  if (ts.isIdentifier(node)) {
    if (context.env.has(node.text)) return context.env.get(node.text);
    if (context.locals.has(node.text)) return inferExpression(context.locals.get(node.text), context, stack);
    throw new Rejection("unresolved_static_dependency_v1");
  }
  if (ts.isPropertyAccessExpression(node)) {
    const parts = propertyPath(node);
    if (parts && context.propertyContracts.has(parts.join("."))) return context.propertyContracts.get(parts.join("."));
    if (parts && context.env.has(parts[0])) {
      let contract = context.env.get(parts[0]);
      for (const name of parts.slice(1)) {
        if (contract.type !== "object" || !contract.properties[name]) throw new Rejection("ambiguous_data_contract_v1");
        contract = contract.properties[name];
      }
      return contract;
    }
    throw new Rejection("unresolved_static_dependency_v1");
  }
  if (ts.isNumericLiteral(node)) {
    const value = Number(node.text);
    if (!Number.isSafeInteger(value)) throw new Rejection("ambiguous_data_contract_v1");
    return { type: "integer", minimum: value, maximum: value };
  }
  if (ts.isStringLiteralLike(node)) return { type: "string", min_length: node.text.length, max_length: node.text.length };
  if (node.kind === ts.SyntaxKind.TrueKeyword || node.kind === ts.SyntaxKind.FalseKeyword) return { type: "boolean" };
  if (ts.isObjectLiteralExpression(node)) {
    const properties = Object.create(null);
    for (const item of node.properties) {
      if (ts.isPropertyAssignment(item) && (ts.isIdentifier(item.name) || ts.isStringLiteralLike(item.name))) {
        const name = checkedContractName(item.name.text, "contract_member_forbidden_v1");
        if (Object.hasOwn(properties, name)) throw new Rejection("ambiguous_data_contract_v1");
        properties[name] = inferExpression(item.initializer, context, stack);
      } else if (ts.isShorthandPropertyAssignment(item)) {
        const name = checkedContractName(item.name.text, "contract_member_forbidden_v1");
        if (Object.hasOwn(properties, name)) throw new Rejection("ambiguous_data_contract_v1");
        properties[name] = inferExpression(item.name, context, stack);
      } else {
        throw new Rejection("ambiguous_data_contract_v1");
      }
    }
    return { type: "object", properties, required: Object.keys(properties).sort(), additional_properties: false };
  }
  if (ts.isArrayLiteralExpression(node)) {
    if (!node.elements.length) throw new Rejection("ambiguous_data_contract_v1");
    const items = node.elements.map((item) => inferExpression(item, context, stack));
    if (items.some((item) => !sameContract(item, items[0]))) throw new Rejection("ambiguous_data_contract_v1");
    return { type: "array", items: items[0], min_items: items.length, max_items: items.length };
  }
  if (ts.isBinaryExpression(node) && [ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken].includes(node.operatorToken.kind)) {
    const left = inferExpression(node.left, context, stack);
    const right = inferExpression(node.right, context, stack);
    if (left.type !== "integer" || right.type !== "integer") throw new Rejection("ambiguous_data_contract_v1");
    let values = [];
    if (node.operatorToken.kind === ts.SyntaxKind.PlusToken) values = [left.minimum + right.minimum, left.maximum + right.maximum];
    if (node.operatorToken.kind === ts.SyntaxKind.MinusToken) values = [left.minimum - right.maximum, left.maximum - right.minimum];
    if (node.operatorToken.kind === ts.SyntaxKind.AsteriskToken) {
      values = [left.minimum * right.minimum, left.minimum * right.maximum, left.maximum * right.minimum, left.maximum * right.maximum];
    }
    if (values.some((item) => !Number.isSafeInteger(item))) throw new Rejection("integer_range_overflow");
    return { type: "integer", minimum: Math.min(...values), maximum: Math.max(...values) };
  }
  if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
    if (node.expression.text === "Number" && node.arguments.length === 1) {
      const parts = propertyPath(node.arguments[0]);
      const contract = parts ? context.propertyContracts.get(parts.join(".")) : null;
      if (contract?.type === "integer") return contract;
      throw new Rejection("ambiguous_data_contract_v1");
    }
    const resolved = resolveFunction(context.modulePath, node.expression.text);
    if (!resolved || stack.has(`${resolved.modulePath}:${resolved.name}`)) throw new Rejection("unresolved_static_dependency_v1");
    if (resolved.node.modifiers?.some((item) => item.kind === ts.SyntaxKind.AsyncKeyword) || resolved.node.asteriskToken) throw new Rejection("async_entrypoint_forbidden");
    const parameters = resolved.node.parameters || [];
    if (parameters.length !== node.arguments.length || parameters.some((item) => !ts.isIdentifier(item.name))) throw new Rejection("unresolved_static_dependency_v1");
    const returns = [];
    function collect(current) {
      if (current !== resolved.node && ts.isFunctionLike(current)) return;
      if (ts.isReturnStatement(current) && current.expression) returns.push(current.expression);
      ts.forEachChild(current, collect);
    }
    if (ts.isArrowFunction(resolved.node) && !ts.isBlock(resolved.node.body)) {
      returns.push(resolved.node.body);
    } else {
      collect(resolved.node.body);
    }
    if (returns.length !== 1) throw new Rejection("unresolved_static_dependency_v1");
    const env = new Map();
    parameters.forEach((item, index) => env.set(item.name.text, inferExpression(node.arguments[index], context, stack)));
    context.dependencies?.set(
      `${context.modulePath}:${node.expression.text}:${resolved.modulePath}:${resolved.name}`,
      {
        type: "static_call",
        from_module: context.modulePath,
        from_symbol: node.expression.text,
        to_module: resolved.modulePath,
        to_symbol: resolved.name,
      },
    );
    const next = new Set(stack).add(`${resolved.modulePath}:${resolved.name}`);
    return inferExpression(returns[0], {
      modulePath: resolved.modulePath,
      env,
      locals: localExpressions(resolved.node),
      propertyContracts: new Map(),
      dependencies: context.dependencies,
    }, next);
  }
  throw new Rejection("ambiguous_data_contract_v1");
}

function findReturns(fn) {
  const rows = [];
  function visit(current) {
    if (current !== fn && ts.isFunctionLike(current)) return;
    if (ts.isReturnStatement(current) && current.expression) rows.push(current.expression);
    ts.forEachChild(current, visit);
  }
  visit(fn.body);
  return rows;
}

function bindingsFor(fn, rootName) {
  const bindings = new Map();
  function visit(current) {
    if (ts.isVariableDeclaration(current) && ts.isIdentifier(current.name) && current.initializer && ts.isCallExpression(current.initializer) && ts.isPropertyAccessExpression(current.initializer.expression)) {
      const call = current.initializer;
      if (ts.isIdentifier(call.expression.expression) && call.expression.expression.text === rootName && ["querySelector", "querySelectorAll"].includes(call.expression.name.text)) {
        const selector = staticString(call.arguments[0]);
        if (!selector) throw new Rejection("dynamic_selector_unsupported_v1");
        if (!htmlSelectors.has(selector)) throw new Rejection("selector_outside_static_root");
        bindings.set(current.name.text, selector);
      }
    }
    ts.forEachChild(current, visit);
  }
  visit(fn.body);
  return bindings;
}

function computationCandidate(record, fn, modules, activationEntrypoint) {
  if (fn.parameters.length !== 1 || !ts.isIdentifier(fn.parameters[0].name) || hasModifier(fn, ts.SyntaxKind.AsyncKeyword) || fn.asteriskToken) throw new Rejection("invalid_compute_signature");
  let forbidden = false;
  function boundary(current) {
    if (ts.isIdentifier(current) && ["document", "window", "globalThis", "Date", "fetch", "setTimeout", "setInterval"].includes(current.text)) forbidden = true;
    if (ts.isPropertyAccessExpression(current) && ts.isIdentifier(current.expression) && current.expression.text === "Math" && current.name.text === "random") forbidden = true;
    ts.forEachChild(current, boundary);
  }
  boundary(fn.body);
  if (forbidden) throw new Rejection("unsupported_extraction_boundary_v1");
  const input = inputContract(fn, [fn.parameters[0].name.text], "computation");
  const dependencies = moduleDependencies(modules);
  const callDependencies = new Map();
  const context = {
    modulePath: record.rel,
    env: new Map([[fn.parameters[0].name.text, input.contract]]),
    locals: localExpressions(fn),
    propertyContracts: new Map(),
    dependencies: callDependencies,
  };
  const outputs = [];
  for (const expression of findReturns(fn)) {
    if (!ts.isObjectLiteralExpression(expression) || objectProperty(expression, "ok")?.kind !== ts.SyntaxKind.TrueKeyword) continue;
    const value = objectProperty(expression, "value");
    if (value) outputs.push(inferExpression(value, context));
  }
  if (!outputs.length || outputs.some((item) => item.type !== "object" || !sameContract(item, outputs[0]))) throw new Rejection("ambiguous_data_contract_v1");
  return baseCandidate("computation", record.rel, activationEntrypoint, modules, input.contract, {
    schema: "data_contract.v1",
    ...outputs[0],
  }, input.errorContract, emptyDomScope(), [...dependencies, ...callDependencies.values()]);
}

function presentationCandidate(record, fn, modules, activationEntrypoint) {
  if (fn.parameters.length !== 2 || fn.parameters.some((item) => !ts.isIdentifier(item.name)) || hasModifier(fn, ts.SyntaxKind.AsyncKeyword) || fn.asteriskToken) throw new Rejection("invalid_render_signature");
  const rootName = fn.parameters[0].name.text;
  const inputName = fn.parameters[1].name.text;
  const bindings = bindingsFor(fn, rootName);
  let updates = 0;
  let eventBinding = false;
  function inspect(current) {
    if (ts.isCallExpression(current) && ts.isPropertyAccessExpression(current.expression) && current.expression.name.text === "addEventListener") eventBinding = true;
    if (ts.isBinaryExpression(current) && current.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isPropertyAccessExpression(current.left) && ts.isIdentifier(current.left.expression) && bindings.has(current.left.expression.text) && ["textContent", "value", "checked", "selectedIndex", "disabled", "hidden"].includes(current.left.name.text)) updates += 1;
    ts.forEachChild(current, inspect);
  }
  inspect(fn.body);
  if (!updates || eventBinding) throw new Rejection("unsupported_extraction_boundary_v1");
  const input = inputContract(fn, [inputName], "presentation");
  return baseCandidate(
    "presentation",
    record.rel,
    activationEntrypoint,
    modules,
    input.contract,
    { schema: "no_output.v1" },
    input.errorContract,
    domScope(bindings, []),
    moduleDependencies(modules),
  );
}

function listenerKey(binding, event, handler) {
  return `${binding}|${event}|${handler}`;
}

function directLocalFunctions(fn) {
  const functions = new Map();
  if (!ts.isBlock(fn.body)) return functions;
  for (const statement of fn.body.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.name && statement.body) {
      if (functions.has(statement.name.text)) throw new Rejection("unsupported_extraction_boundary_v1");
      functions.set(statement.name.text, statement);
    }
    if (!ts.isVariableStatement(statement) || (statement.declarationList.flags & ts.NodeFlags.Const) === 0) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (ts.isIdentifier(declaration.name)
          && declaration.initializer
          && (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer))) {
        if (functions.has(declaration.name.text)) throw new Rejection("unsupported_extraction_boundary_v1");
        functions.set(declaration.name.text, declaration.initializer);
      }
    }
  }
  return functions;
}

function assertEntryLocalFunctionClosure(fn, capabilityKind) {
  if (!ts.isBlock(fn.body)) return;
  const localFunctions = directLocalFunctions(fn);
  const localNodes = new Set(localFunctions.values());
  const finalStatement = fn.body.statements.at(-1);
  const inlineDispose = capabilityKind === "interaction"
    && ts.isReturnStatement(finalStatement)
    && finalStatement.expression
    && (ts.isArrowFunction(finalStatement.expression) || ts.isFunctionExpression(finalStatement.expression))
    ? finalStatement.expression
    : null;
  const roleAnchors = new Set();
  if (capabilityKind === "interaction") {
    if (ts.isReturnStatement(finalStatement)
        && ts.isIdentifier(finalStatement.expression)
        && localFunctions.has(finalStatement.expression.text)) {
      roleAnchors.add(finalStatement.expression.text);
    }
    function collectListenerHandlers(current) {
      if (ts.isFunctionLike(current)) return;
      if (ts.isCallExpression(current)
          && ts.isPropertyAccessExpression(current.expression)
          && current.expression.name.text === "addEventListener"
          && ts.isIdentifier(current.arguments[1])
          && localFunctions.has(current.arguments[1].text)) {
        roleAnchors.add(current.arguments[1].text);
      }
      ts.forEachChild(current, collectListenerHandlers);
    }
    collectListenerHandlers(fn.body);
  }
  if ([...localFunctions.keys()].some((name) => !roleAnchors.has(name))) {
    throw new Rejection("unsupported_extraction_boundary_v1");
  }

  function assertNoShadowedLocal(parameters) {
    if (parameters.some((item) => ts.isIdentifier(item.name) && localFunctions.has(item.name.text))) {
      throw new Rejection("unsupported_extraction_boundary_v1");
    }
  }

  function scan(current, allowInlineDispose) {
    if (ts.isFunctionLike(current)) {
      if (localNodes.has(current)) return;
      if (allowInlineDispose && current === inlineDispose) {
        assertNoShadowedLocal(current.parameters);
        ts.forEachChild(current, (child) => scan(child, false));
        return;
      }
      throw new Rejection("unsupported_extraction_boundary_v1");
    }
    if (ts.isVariableDeclaration(current)
        && ts.isIdentifier(current.name)
        && localFunctions.has(current.name.text)
        && localFunctions.get(current.name.text) !== current.initializer) {
      throw new Rejection("unsupported_extraction_boundary_v1");
    }
    ts.forEachChild(current, (child) => scan(child, allowInlineDispose));
  }

  assertNoShadowedLocal(fn.parameters);
  scan(fn.body, true);
  for (const name of roleAnchors) {
    const local = localFunctions.get(name);
    if (!local?.body) throw new Rejection("unsupported_extraction_boundary_v1");
    assertNoShadowedLocal(local.parameters);
    scan(local.body, false);
  }

  const localBindings = new Map();
  function collectBindings(current) {
    if (ts.isVariableDeclaration(current)
        && ts.isIdentifier(current.name)
        && current.initializer
        && !ts.isFunctionLike(current.initializer)) {
      if (localBindings.has(current.name.text)) {
        throw new Rejection("unsupported_extraction_boundary_v1");
      }
      localBindings.set(current.name.text, current);
    }
    ts.forEachChild(current, collectBindings);
  }
  collectBindings(fn.body);
  const requiredBindings = new Set();
  function collectRequired(current) {
    if (ts.isIdentifier(current)
        && localBindings.has(current.text)
        && localBindings.get(current.text).name !== current
        && isSymbolReference(current)) {
      requiredBindings.add(current.text);
    }
    ts.forEachChild(current, collectRequired);
  }

  function allowedEffect(statement) {
    if (!ts.isExpressionStatement(statement)) return true;
    const expression = statement.expression;
    if (ts.isBinaryExpression(expression)
        && expression.operatorToken.kind === ts.SyntaxKind.EqualsToken
        && ts.isPropertyAccessExpression(expression.left)
        && ["checked", "disabled", "hidden", "selectedIndex", "textContent", "value"]
          .includes(expression.left.name.text)) {
      return true;
    }
    if (!ts.isCallExpression(expression) || !ts.isPropertyAccessExpression(expression.expression)) {
      return false;
    }
    return [
      "addEventListener",
      "emit",
      "preventDefault",
      "removeEventListener",
    ].includes(expression.expression.name.text);
  }
  function assertEffects(current) {
    if (ts.isVariableStatement(current)
        && (current.declarationList.flags & ts.NodeFlags.Const) === 0) {
      throw new Rejection("unsupported_extraction_boundary_v1");
    }
    if (ts.isIfStatement(current)
        && (current.elseStatement || !returnedStatement(current.thenStatement))) {
      throw new Rejection("unsupported_extraction_boundary_v1");
    }
    if (ts.isStatement(current)
        && !ts.isBlock(current)
        && !ts.isEmptyStatement(current)
        && !ts.isExpressionStatement(current)
        && !ts.isFunctionDeclaration(current)
        && !ts.isIfStatement(current)
        && !ts.isReturnStatement(current)
        && !ts.isVariableStatement(current)) {
      throw new Rejection("unsupported_extraction_boundary_v1");
    }
    if (ts.isExpressionStatement(current) && !allowedEffect(current)) {
      throw new Rejection("unsupported_extraction_boundary_v1");
    }
    if (ts.isReturnStatement(current) && current.expression) collectRequired(current.expression);
    if (ts.isExpressionStatement(current) && allowedEffect(current)) collectRequired(current.expression);
    if (ts.isIfStatement(current) && returnedStatement(current.thenStatement)) {
      collectRequired(current.expression);
    }
    ts.forEachChild(current, assertEffects);
  }
  assertEffects(fn.body);
  const pendingBindings = [...requiredBindings];
  while (pendingBindings.length) {
    const name = pendingBindings.pop();
    const declaration = localBindings.get(name);
    if (!declaration) continue;
    const before = new Set(requiredBindings);
    collectRequired(declaration.initializer);
    for (const dependency of requiredBindings) {
      if (!before.has(dependency)) pendingBindings.push(dependency);
    }
  }
  if ([...localBindings.keys()].some((name) => !requiredBindings.has(name))) {
    throw new Rejection("unsupported_extraction_boundary_v1");
  }
}

function returnedDispose(fn, localFunctions) {
  if (!ts.isBlock(fn.body)) throw new Rejection("interaction_dispose_not_closed");
  const returns = [];
  function visit(current) {
    if (current !== fn.body && ts.isFunctionLike(current)) return;
    if (ts.isReturnStatement(current)) {
      returns.push(current);
      return;
    }
    ts.forEachChild(current, visit);
  }
  visit(fn.body);
  const finalStatement = fn.body.statements.at(-1);
  if (returns.length !== 1 || returns[0] !== finalStatement || !returns[0].expression) {
    throw new Rejection("interaction_dispose_not_closed");
  }
  let dispose = returns[0].expression;
  if (ts.isIdentifier(dispose)) dispose = localFunctions.get(dispose.text);
  if (!dispose
      || !(ts.isArrowFunction(dispose) || ts.isFunctionExpression(dispose) || ts.isFunctionDeclaration(dispose))
      || dispose.parameters.length
      || hasModifier(dispose, ts.SyntaxKind.AsyncKeyword)
      || dispose.asteriskToken
      || !ts.isBlock(dispose.body)) {
    throw new Rejection("interaction_dispose_not_closed");
  }
  return dispose;
}

function listenerDescriptor(call, bindings, handlers) {
  const owner = call.expression.expression;
  const event = staticString(call.arguments[0]);
  const handler = call.arguments[1];
  if (!ts.isIdentifier(owner)
      || !bindings.has(owner.text)
      || call.arguments.length !== 2
      || !event
      || !["click", "input", "change", "select", "submit", "reset"].includes(event)
      || !ts.isIdentifier(handler)
      || !handlers.has(handler.text)) {
    throw new Rejection("event_binding_unsupported_v1");
  }
  return {
    binding: owner.text,
    event,
    handler: handler.text,
    key: listenerKey(owner.text, event, handler.text),
  };
}

function mountListeners(fn, bindings, handlers) {
  const added = new Map();
  for (const statement of fn.body.statements) {
    function visit(current) {
      if (ts.isFunctionLike(current)) return;
      if (ts.isCallExpression(current) && ts.isPropertyAccessExpression(current.expression)) {
        const method = current.expression.name.text;
        if (method === "removeEventListener") throw new Rejection("interaction_dispose_not_closed");
        if (method === "addEventListener") {
          if (!ts.isExpressionStatement(statement) || statement.expression !== current) {
            throw new Rejection("event_binding_unsupported_v1");
          }
          const descriptor = listenerDescriptor(current, bindings, handlers);
          added.set(descriptor.key, descriptor);
        }
      }
      ts.forEachChild(current, visit);
    }
    visit(statement);
  }
  return added;
}

function disposeListeners(dispose, bindings, handlers) {
  const removed = new Set();
  for (const statement of dispose.body.statements) {
    if (!ts.isExpressionStatement(statement)
        || !ts.isCallExpression(statement.expression)
        || !ts.isPropertyAccessExpression(statement.expression.expression)
        || statement.expression.expression.name.text !== "removeEventListener") {
      throw new Rejection("interaction_dispose_not_closed");
    }
    const key = listenerDescriptor(statement.expression, bindings, handlers).key;
    if (removed.has(key)) throw new Rejection("interaction_dispose_not_closed");
    removed.add(key);
  }
  return removed;
}

function numericDomLocal(declaration, bindings) {
  if (!ts.isIdentifier(declaration.name)
      || !declaration.initializer
      || !ts.isCallExpression(declaration.initializer)
      || !ts.isIdentifier(declaration.initializer.expression)
      || declaration.initializer.expression.text !== "Number"
      || declaration.initializer.arguments.length !== 1) return null;
  const value = declaration.initializer.arguments[0];
  if (!ts.isPropertyAccessExpression(value)
      || value.name.text !== "value"
      || !ts.isIdentifier(value.expression)
      || !bindings.has(value.expression.text)) return null;
  return declaration.name.text;
}

function guardReturns(statement) {
  if (ts.isReturnStatement(statement)) return statement.expression === undefined;
  return ts.isBlock(statement)
    && statement.statements.length === 1
    && ts.isReturnStatement(statement.statements[0])
    && statement.statements[0].expression === undefined;
}

function numericGuardContract(expression, name) {
  const atoms = flattenOr(expression);
  if (atoms.length !== 3) return null;
  let integer = false;
  let minimum = null;
  let maximum = null;
  for (let atom of atoms) {
    while (ts.isParenthesizedExpression(atom)) atom = atom.expression;
    if (ts.isPrefixUnaryExpression(atom)
        && atom.operator === ts.SyntaxKind.ExclamationToken
        && ts.isCallExpression(atom.operand)
        && ts.isPropertyAccessExpression(atom.operand.expression)
        && ts.isIdentifier(atom.operand.expression.expression)
        && atom.operand.expression.expression.text === "Number"
        && atom.operand.expression.name.text === "isInteger"
        && atom.operand.arguments.length === 1
        && ts.isIdentifier(atom.operand.arguments[0])
        && atom.operand.arguments[0].text === name) {
      if (integer) return null;
      integer = true;
      continue;
    }
    if (!ts.isBinaryExpression(atom)
        || !ts.isIdentifier(atom.left)
        || atom.left.text !== name) return null;
    const value = numericLiteral(atom.right);
    if (value === null || !Number.isSafeInteger(value)) return null;
    if (atom.operatorToken.kind === ts.SyntaxKind.LessThanToken && minimum === null) {
      minimum = value;
    } else if (atom.operatorToken.kind === ts.SyntaxKind.GreaterThanToken && maximum === null) {
      maximum = value;
    } else {
      return null;
    }
  }
  return integer
    && Number.isSafeInteger(minimum)
    && Number.isSafeInteger(maximum)
    && minimum <= maximum
    ? { type: "integer", minimum, maximum }
    : null;
}

function handlerEmits(handler, record, portsName, bindings, propertyContracts, callDependencies) {
  if (!ts.isBlock(handler.body)) throw new Rejection("event_output_unsupported_v1");
  const numericLocals = new Map();
  const guarded = new Map();
  const emits = [];
  const statements = [...handler.body.statements];
  for (let index = 0; index < statements.length; index += 1) {
    const statement = statements[index];
    if (ts.isVariableStatement(statement) && (statement.declarationList.flags & ts.NodeFlags.Const) !== 0) {
      for (const declaration of statement.declarationList.declarations) {
        const name = numericDomLocal(declaration, bindings);
        if (name) numericLocals.set(name, index);
      }
    }
    if (ts.isIfStatement(statement) && !statement.elseStatement && guardReturns(statement.thenStatement)) {
      for (const [name, declarationIndex] of numericLocals) {
        if (declarationIndex >= index) continue;
        const contract = numericGuardContract(statement.expression, name);
        if (contract) guarded.set(name, { index, contract });
      }
    }
    function inspect(current) {
      if (ts.isFunctionLike(current)) return;
      if (ts.isCallExpression(current)
          && ts.isPropertyAccessExpression(current.expression)
          && current.expression.name.text === "emit"
          && ts.isIdentifier(current.expression.expression)
          && current.expression.expression.text === portsName) {
        if (!ts.isExpressionStatement(statement) || statement.expression !== current) {
          throw new Rejection("event_output_unsupported_v1");
        }
        const name = checkedContractName(
          staticString(current.arguments[0]),
          "event_output_unsupported_v1",
        );
        if (current.arguments.length !== 2) throw new Rejection("event_output_unsupported_v1");
        const env = new Map();
        for (const [local, evidence] of guarded) {
          if (evidence.index < index) env.set(local, evidence.contract);
        }
        const contract = inferExpression(current.arguments[1], {
          modulePath: record.rel,
          env,
          locals: localExpressions(handler),
          propertyContracts,
          dependencies: callDependencies,
        });
        if (contract.type !== "object") throw new Rejection("ambiguous_data_contract_v1");
        emits.push({ name, contract });
      }
      ts.forEachChild(current, inspect);
    }
    inspect(statement);
  }
  return emits;
}

function interactionCandidate(record, fn, modules, activationEntrypoint) {
  if (fn.parameters.length !== 2 || fn.parameters.some((item) => !ts.isIdentifier(item.name)) || hasModifier(fn, ts.SyntaxKind.AsyncKeyword) || fn.asteriskToken) throw new Rejection("invalid_mount_signature");
  const rootName = fn.parameters[0].name.text;
  const portsName = fn.parameters[1].name.text;
  const bindings = bindingsFor(fn, rootName);
  const handlers = directLocalFunctions(fn);
  const dispose = returnedDispose(fn, handlers);
  const added = mountListeners(fn, bindings, handlers);
  const removed = disposeListeners(dispose, bindings, handlers);
  if (!added.size
      || [...added.keys()].some((item) => !removed.has(item))
      || [...removed].some((item) => !added.has(item))) {
    throw new Rejection("interaction_dispose_not_closed");
  }
  const emits = new Map();
  const callDependencies = new Map();
  const propertyContracts = new Map();
  for (const [binding, selector] of bindings) {
    const control = htmlControls[selector];
    if (control?.checked_contract) propertyContracts.set(`${binding}.checked`, control.checked_contract);
  }
  for (const handlerName of new Set([...added.values()].map((item) => item.handler))) {
    for (const { name, contract } of handlerEmits(
      handlers.get(handlerName), record, portsName, bindings, propertyContracts, callDependencies,
    )) {
      if (emits.has(name) && !sameContract(emits.get(name), contract)) throw new Rejection("ambiguous_data_contract_v1");
      emits.set(name, contract);
    }
  }
  if (!emits.size) throw new Rejection("event_output_unsupported_v1");
  const input = inputContract(fn, [portsName, "input"], "interaction");
  const outputEvents = Object.create(null);
  for (const [name, contract] of [...emits].sort()) outputEvents[name] = { schema: "data_contract.v1", ...contract };
  return baseCandidate(
    "interaction",
    record.rel,
    activationEntrypoint,
    modules,
    input.contract,
    { schema: "event_outputs.v1", events: outputEvents },
    input.errorContract,
    domScope(bindings, [...new Set([...added.values()].map((item) => item.event))]),
    [...moduleDependencies(modules), ...callDependencies.values()],
  );
}

function emptyDomScope() {
  return { root_contract: "capsule_root", selectors: [], classes: [], attributes: [], events: [] };
}

function domScope(bindings, events) {
  return {
    root_contract: "capsule_root",
    selectors: [...new Set(bindings.values())].sort(),
    classes: [],
    attributes: [],
    events: [...new Set(events)].sort(),
  };
}

function moduleDependencies(modules) {
  const included = new Set(modules);
  const rows = [];
  for (const relative of modules) {
    for (const dependency of moduleCache.get(relative).imports) {
      if (included.has(dependency)) rows.push({ type: "static_import", from_module: relative, to_module: dependency });
    }
  }
  return rows;
}

function baseCandidate(kind, entryModule, entrypoint, modules, inputContractValue, outputContract, errorContract, scope, dependencies) {
  const modes = {
    presentation: "declared_input_render",
    interaction: "declared_event_mount",
    computation: "declared_input_compute",
  };
  return {
    capability_kind: kind,
    activation: { mode: modes[kind], entry_module: entryModule, entrypoint },
    input_contract: inputContractValue,
    output_contract: outputContract,
    error_contract: errorContract,
    dom_scope: scope,
    dependencies,
    javascript_modules: modules.map((relative) => ({ path: relative, source: moduleCache.get(relative).source })),
  };
}

const roleEntrypoints = [
  ["render", "presentation"],
  ["mount", "interaction"],
  ["compute", "computation"],
];

function exportedRoleSeeds(record) {
  const seeds = [];
  for (const [entrypoint, kind] of roleEntrypoints) {
    let exposeAlias = false;
    let local = record.exports.get(entrypoint);
    if (!local && record.exports.get("default") === entrypoint) {
      local = record.exports.get("default");
      exposeAlias = true;
    }
    if (local) seeds.push({ entrypoint, kind, activationEntrypoint: entrypoint, local, exposeAlias });
  }
  return seeds;
}

function implicitRoleSeeds(record) {
  const seeds = [];
  for (const [local, fn] of record.functions) {
    if (fn.parameters.length === 1) {
      seeds.push({ entrypoint: "compute", kind: "computation", activationEntrypoint: "compute", local });
    }
    if (fn.parameters.length === 2) {
      seeds.push({ entrypoint: "render", kind: "presentation", activationEntrypoint: "render", local });
      seeds.push({ entrypoint: "mount", kind: "interaction", activationEntrypoint: "mount", local });
    }
  }
  return seeds;
}

function exposeImplicitEntrypoint(candidate, record, local, entrypoint) {
  const suffix = record.source.endsWith("\n") ? "" : "\n";
  const source = `${record.source}${suffix}export { ${local} as ${entrypoint} };\n`;
  candidate.javascript_modules = candidate.javascript_modules.map((module) => (
    module.path === record.rel ? { ...module, source } : module
  ));
  return candidate;
}

function buildRoleCandidate(record, modules, seed) {
  const { entrypoint, kind, activationEntrypoint, local } = seed;
  const literalEvidence = assertAtomicSymbolClosure(record, local, modules, kind);
  const fn = record.functions.get(local);
  if (!fn?.body) throw new Rejection(`invalid_${entrypoint}_signature`);
  assertEntryLocalFunctionClosure(fn, kind);
  let candidate = null;
  if (kind === "presentation") candidate = presentationCandidate(record, fn, modules, activationEntrypoint);
  if (kind === "interaction") candidate = interactionCandidate(record, fn, modules, activationEntrypoint);
  if (kind === "computation") candidate = computationCandidate(record, fn, modules, activationEntrypoint);
  assertCandidateSymbolCoverage(record, local, modules, candidate);
  candidate.literal_values = literalEvidence.literalValues;
  candidate.composed_literal_values = literalEvidence.composedLiteralValues;
  return candidate;
}

function analyzeEntry(entry) {
  const modules = moduleClosure(entry);
  const record = moduleCache.get(normalizeRel(entry));
  const candidates = [];
  const rejections = [];
  const explicitSeeds = exportedRoleSeeds(record);
  const seeds = explicitSeeds.length ? explicitSeeds : implicitRoleSeeds(record);
  const closureKinds = new Set(
    modules.flatMap((relative) => exportedRoleSeeds(moduleCache.get(relative)).map((item) => item.kind)),
  );
  if (seeds.length && closureKinds.size > 1) {
    return {
      candidates: [],
      rejections: seeds.map(({ entrypoint, kind }) => ({
        entry_module: record.rel,
        entrypoint,
        capability_kind: kind,
        error_code: "non_atomic_role_closure_v1",
      })),
    };
  }
  for (const { entrypoint, kind, activationEntrypoint, local, exposeAlias } of seeds) {
    try {
      let candidate = buildRoleCandidate(
        record,
        modules,
        { entrypoint, kind, activationEntrypoint, local },
      );
      if (!explicitSeeds.length || exposeAlias) {
        candidate = exposeImplicitEntrypoint(candidate, record, local, entrypoint);
      }
      candidates.push(candidate);
    } catch (error) {
      if (!(error instanceof Rejection)) throw error;
      if (explicitSeeds.length) {
        rejections.push({ entry_module: record.rel, entrypoint, capability_kind: kind, error_code: error.code });
      }
    }
  }
  if (!explicitSeeds.length && candidates.length > 1) {
    return {
      candidates: [],
      rejections: candidates.map((candidate) => ({
        entry_module: record.rel,
        entrypoint: candidate.activation.entrypoint,
        capability_kind: candidate.capability_kind,
        error_code: "non_atomic_role_closure_v1",
      })),
    };
  }
  if (!candidates.length && !rejections.length) rejections.push({ entry_module: record.rel, entrypoint: null, capability_kind: null, error_code: "missing_supported_entrypoint_v1" });
  return { candidates, rejections };
}

try {
  initializeModuleSnapshot();
  const candidates = [];
  const rejections = [];
  for (const entry of [...new Set(entryModules)].sort()) {
    try {
      const result = analyzeEntry(entry);
      candidates.push(...result.candidates);
      rejections.push(...result.rejections);
    } catch (error) {
      if (!(error instanceof Rejection)) throw error;
      rejections.push({ entry_module: String(entry), entrypoint: null, capability_kind: null, error_code: error.code, logical_path: error.logicalPath || null });
    }
  }
  process.stdout.write(JSON.stringify({ schema_version: "extraction_ast.v1", status: "ok", candidates, rejections }));
} catch {
  process.stdout.write(JSON.stringify({ schema_version: "extraction_ast.v1", status: "failed", error_code: "extraction_analyzer_failed" }));
}
