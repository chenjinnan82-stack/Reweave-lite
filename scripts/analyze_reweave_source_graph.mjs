import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import * as esbuild from "esbuild";
import * as ts from "typescript";

const SOURCE_GRAPH_VERSION = "source_graph.v1";
const REQUEST_SCHEMA = "source_graph_request.v1";
const VIRTUAL_ROOT = "/__reweave_snapshot__";
const INTRINSIC_PATH = "/__reweave_intrinsic__.d.ts";
const MAX_SAFE = Number.MAX_SAFE_INTEGER;
const CAPTURE_BUNDLE_CONTRACT_VERSION = "reweave_capture_bundle.v1";
const CAPTURE_ENTRY = "__reweave_capture_entry__.js";
const SELECTED_LOGICAL_PATH = "__reweave_capture__/selected.js";
const FIXED_ESBUILD_VERSION = "0.28.1";
const MAX_SELECTED_BYTES = 1024 * 1024;
const CAPTURE_BUNDLE_OPTIONS = Object.freeze({
  bundle: true,
  treeShaking: true,
  format: "esm",
  platform: "neutral",
  target: "es2022",
  write: false,
  minify: false,
  metafile: true,
  sourcemap: false,
  legalComments: "none",
  external: [],
  charset: "utf8",
  logLevel: "silent",
  resolveExtensions: [],
  mainFields: [],
  conditions: [],
  packages: "bundle",
  tsconfigRaw: { compilerOptions: {} },
});

class Rejection extends Error {
  constructor(code, logicalPath = null) {
    super(code);
    this.code = code;
    this.logicalPath = typeof logicalPath === "string" ? logicalPath : null;
  }
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value && typeof value === "object") {
    const output = {};
    for (const key of Object.keys(value).sort()) output[key] = canonicalValue(value[key]);
    return output;
  }
  if (typeof value === "number" && !Number.isFinite(value)) throw new Rejection("unclassified_internal_result");
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalValue(value));
}

function canonicalSha256(value) {
  return crypto.createHash("sha256").update(canonicalJson(value), "utf8").digest("hex");
}

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function compareUtf8(left, right) {
  return Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8"));
}

function normalizedLogicalPath(value) {
  const raw = typeof value === "string" ? value : "";
  if (!raw || raw.includes("\\") || path.posix.isAbsolute(raw) || raw.endsWith("/")) {
    throw new Rejection("closure_unproven");
  }
  const parts = raw.split("/");
  if (parts.some((part) => !part || part === "." || part === ".." || /[\u0000-\u001f\u007f]/u.test(part))) {
    throw new Rejection("closure_unproven");
  }
  if (!/\.(?:js|mjs)$/u.test(raw)) throw new Rejection("closure_unproven", raw);
  return raw;
}

function strictBase64(value, logicalPath) {
  if (typeof value !== "string" || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u.test(value)) {
    throw new Rejection("source_changed", logicalPath);
  }
  const bytes = Buffer.from(value, "base64");
  if (bytes.toString("base64") !== value) throw new Rejection("source_changed", logicalPath);
  return bytes;
}

function strictUtf8(bytes, logicalPath) {
  try {
    return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new Rejection("source_utf8_invalid", logicalPath);
  }
}

function utf16ByteMap(source, logicalPath) {
  const offsets = new Array(source.length + 1).fill(null);
  let utf16 = 0;
  let byte = 0;
  offsets[0] = 0;
  for (const scalar of source) {
    const width16 = scalar.length;
    const width8 = Buffer.byteLength(scalar, "utf8");
    if (width16 === 2) offsets[utf16 + 1] = null;
    utf16 += width16;
    byte += width8;
    offsets[utf16] = byte;
  }
  if (utf16 !== source.length || offsets[source.length] !== Buffer.byteLength(source, "utf8")) {
    throw new Rejection("source_span_invalid", logicalPath);
  }
  return offsets;
}

function byteOffset(record, utf16) {
  const value = Number.isInteger(utf16) ? record.offsets[utf16] : null;
  if (!Number.isInteger(value)) throw new Rejection("source_span_invalid", record.logicalPath);
  return value;
}

function virtualName(logicalPath) {
  return `${VIRTUAL_ROOT}/${logicalPath}`;
}

function logicalFromVirtual(fileName) {
  const prefix = `${VIRTUAL_ROOT}/`;
  return fileName.startsWith(prefix) ? fileName.slice(prefix.length) : null;
}

function hasModifier(node, kind) {
  return Boolean(node.modifiers?.some((modifier) => modifier.kind === kind));
}

function syntaxKindName(node) {
  if (ts.isVariableStatement(node)) return "VariableStatement";
  if (ts.isExpressionStatement(node)) return "ExpressionStatement";
  if (ts.isIfStatement(node)) return "IfStatement";
  if (ts.isClassDeclaration(node)) return "ClassDeclaration";
  return ts.SyntaxKind[node.kind] || "Unknown";
}

function bindingDeclarationSpan(node, sourceFile) {
  if ((ts.isFunctionExpression(node) || ts.isArrowFunction(node)) &&
      ts.isVariableDeclaration(node.parent) && ts.isIdentifier(node.parent.name)) {
    return [node.parent.getStart(sourceFile, false), node.parent.end];
  }
  return [node.getStart(sourceFile, false), node.end];
}

function declarationNameNode(node) {
  if (ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node)) return node.name || null;
  if (ts.isVariableDeclaration(node) || ts.isParameter(node)) return ts.isIdentifier(node.name) ? node.name : null;
  return null;
}

function containingFunction(node) {
  let current = node.parent;
  while (current) {
    if (ts.isFunctionLike(current)) return current;
    current = current.parent;
  }
  return null;
}

function isDeclarationIdentifier(node) {
  const parent = node.parent;
  return Boolean(
    ((ts.isFunctionDeclaration(parent) || ts.isFunctionExpression(parent) || ts.isClassDeclaration(parent) ||
      ts.isVariableDeclaration(parent) || ts.isParameter(parent) || ts.isImportSpecifier(parent) ||
      ts.isImportClause(parent) || ts.isNamespaceImport(parent) || ts.isBindingElement(parent)) && parent.name === node)
    || (ts.isPropertyAccessExpression(parent) && parent.name === node)
    || (ts.isPropertyAssignment(parent) && parent.name === node && !parent.shorthand)
    || (ts.isExportSpecifier(parent) && parent.name === node)
    || (ts.isImportSpecifier(parent) && parent.propertyName === node)
    || (ts.isLabeledStatement(parent) && parent.label === node)
    || (ts.isBreakOrContinueStatement(parent) && parent.label === node)
  );
}

function isWriteIdentifier(node) {
  const parent = node.parent;
  if (ts.isBinaryExpression(parent) && parent.left === node &&
      parent.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
      parent.operatorToken.kind <= ts.SyntaxKind.LastAssignment) return true;
  return (ts.isPrefixUnaryExpression(parent) || ts.isPostfixUnaryExpression(parent)) &&
    parent.operand === node && [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(parent.operator);
}

function createSnapshot(request) {
  if (!Array.isArray(request.module_snapshot) || request.module_snapshot.length === 0) {
    throw new Rejection("source_changed");
  }
  const records = new Map();
  const foldedPaths = new Map();
  const approximatePaths = new Map();
  for (const raw of request.module_snapshot) {
    if (!raw || typeof raw !== "object") throw new Rejection("source_changed");
    const logicalPath = normalizedLogicalPath(raw.path);
    if (records.has(logicalPath)) throw new Rejection("source_path_normalization_conflict", logicalPath);
    const folded = logicalPath.toLocaleLowerCase("en-US");
    if (foldedPaths.has(folded) && foldedPaths.get(folded) !== logicalPath) {
      throw new Rejection("source_path_normalization_conflict", logicalPath);
    }
    foldedPaths.set(folded, logicalPath);
    const approximate = logicalPath.normalize("NFC").toLocaleLowerCase("en-US");
    if (approximatePaths.has(approximate) && approximatePaths.get(approximate) !== logicalPath) {
      throw new Rejection("source_path_normalization_conflict", logicalPath);
    }
    approximatePaths.set(approximate, logicalPath);
    const bytes = strictBase64(raw.source_base64, logicalPath);
    if (bytes.length > 1024 * 1024 || typeof raw.sha256 !== "string" ||
        !/^[0-9a-f]{64}$/u.test(raw.sha256) || sha256Bytes(bytes) !== raw.sha256) {
      throw new Rejection("source_changed", logicalPath);
    }
    const source = strictUtf8(bytes, logicalPath);
    records.set(logicalPath, {
      logicalPath,
      bytes,
      source,
      sha256: raw.sha256,
      offsets: utf16ByteMap(source, logicalPath),
      sourceFile: null,
      resolution: new Map(),
    });
  }
  const symlinks = new Set();
  if (!Array.isArray(request.symlinks)) throw new Rejection("source_changed");
  for (const raw of request.symlinks) {
    const value = typeof raw === "string" ? raw : raw?.path;
    if (typeof value !== "string" || !value || value.includes("\\") || path.posix.isAbsolute(value)) {
      throw new Rejection("source_changed");
    }
    const normalized = path.posix.normalize(value);
    if (normalized === "." || normalized === ".." || normalized.startsWith("../")) throw new Rejection("source_changed");
    symlinks.add(normalized);
  }
  return { records, foldedPaths, approximatePaths, symlinks };
}

function pathUsesSymlink(logicalPath, symlinks) {
  const parts = logicalPath.split("/");
  let current = "";
  for (const part of parts) {
    current = current ? `${current}/${part}` : part;
    if (symlinks.has(current)) return true;
  }
  return false;
}

function resolveSpecifier(snapshot, fromPath, specifier, node = null) {
  if (typeof specifier !== "string" || !specifier || specifier.includes("?") || specifier.includes("#") ||
      /^(?:[A-Za-z][A-Za-z0-9+.-]*:|\/)/u.test(specifier) ||
      (!specifier.startsWith("./") && !specifier.startsWith("../"))) {
    throw new Rejection("closure_unproven", fromPath);
  }
  const joined = path.posix.normalize(path.posix.join(path.posix.dirname(fromPath), specifier));
  if (joined === ".." || joined.startsWith("../") || joined.includes("\\")) throw new Rejection("closure_unproven", fromPath);
  if (/(?:^|\/)index\.(?:js|mjs)$/u.test(joined)) throw new Rejection("closure_unproven", fromPath);
  const candidates = /\.(?:js|mjs)$/u.test(joined) ? [joined] : [`${joined}.js`, `${joined}.mjs`];
  const matches = candidates.filter((candidate) => snapshot.records.has(candidate));
  if (matches.length > 1) throw new Rejection("closure_unproven", fromPath);
  if (matches.length === 0) {
    const approximate = candidates.find((candidate) => (
      snapshot.foldedPaths.has(candidate.toLocaleLowerCase("en-US")) ||
      snapshot.approximatePaths.has(candidate.normalize("NFC").toLocaleLowerCase("en-US"))
    ));
    if (approximate) throw new Rejection("import_path_spelling_mismatch", fromPath);
    throw new Rejection("closure_unproven", fromPath);
  }
  const resolved = matches[0];
  if (pathUsesSymlink(resolved, snapshot.symlinks)) throw new Rejection("closure_symlink_forbidden", fromPath);
  return resolved;
}

function validateModuleSyntax(record, snapshot) {
  const sourceFile = record.sourceFile;
  if (sourceFile.parseDiagnostics.length > 0) throw new Rejection("closure_unproven", record.logicalPath);
  const imports = [];
  const dynamicDependencies = [];
  const explicitExportNames = new Set();
  function registerExplicitExport(publicName) {
    if (explicitExportNames.has(publicName)) {
      throw new Rejection("closure_unproven", record.logicalPath);
    }
    explicitExportNames.add(publicName);
  }
  for (const statement of sourceFile.statements) {
    const modifiers = statement.modifiers || [];
    const hasExportModifier = modifiers.some((item) => item.kind === ts.SyntaxKind.ExportKeyword);
    const hasDefaultModifier = modifiers.some((item) => item.kind === ts.SyntaxKind.DefaultKeyword);
    if (hasExportModifier) {
      if (hasDefaultModifier) {
        registerExplicitExport("default");
      } else if (ts.isVariableStatement(statement)) {
        for (const declaration of statement.declarationList.declarations) {
          if (!ts.isIdentifier(declaration.name)) throw new Rejection("closure_unproven", record.logicalPath);
          registerExplicitExport(declaration.name.text);
        }
      } else if ((ts.isFunctionDeclaration(statement) || ts.isClassDeclaration(statement)) && statement.name) {
        registerExplicitExport(statement.name.text);
      }
    }
    if (ts.isImportDeclaration(statement)) {
      if (!statement.importClause || !ts.isStringLiteral(statement.moduleSpecifier) ||
          statement.assertClause || statement.attributes ||
          (statement.importClause.namedBindings && ts.isNamespaceImport(statement.importClause.namedBindings))) {
        throw new Rejection("closure_unproven", record.logicalPath);
      }
      const resolved = resolveSpecifier(snapshot, record.logicalPath, statement.moduleSpecifier.text, statement);
      record.resolution.set(statement.moduleSpecifier.text, resolved);
      imports.push({ specifier: statement.moduleSpecifier.text, logical_path: resolved });
    } else if (ts.isExportDeclaration(statement)) {
      if (!statement.exportClause || !ts.isNamedExports(statement.exportClause)) {
        throw new Rejection("closure_unproven", record.logicalPath);
      }
      for (const element of statement.exportClause.elements) {
        if (!ts.isIdentifier(element.name) || (element.propertyName && !ts.isIdentifier(element.propertyName))) {
          throw new Rejection("invalid_export_identifier", record.logicalPath);
        }
        registerExplicitExport(element.name.text);
      }
      if (statement.moduleSpecifier) {
        if (!ts.isStringLiteral(statement.moduleSpecifier)) throw new Rejection("closure_unproven", record.logicalPath);
        const resolved = resolveSpecifier(snapshot, record.logicalPath, statement.moduleSpecifier.text, statement);
        record.resolution.set(statement.moduleSpecifier.text, resolved);
        imports.push({ specifier: statement.moduleSpecifier.text, logical_path: resolved, reexport: true });
      }
    } else if (ts.isExportAssignment(statement)) {
      registerExplicitExport("default");
      if (statement.isExportEquals || (!ts.isIdentifier(statement.expression) && !ts.isFunctionExpression(statement.expression))) {
        throw new Rejection("closure_unproven", record.logicalPath);
      }
    }
  }
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      dynamicDependencies.push({ kind: "dynamic_import" });
    }
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "require") {
      throw new Rejection("closure_unproven", record.logicalPath);
    }
    if (ts.isBinaryExpression(node) && ts.isPropertyAccessExpression(node.left) &&
        ts.isIdentifier(node.left.expression) && ["module", "exports"].includes(node.left.expression.text)) {
      throw new Rejection("closure_unproven", record.logicalPath);
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  record.imports = imports.sort((a, b) => compareUtf8(a.logical_path, b.logical_path));
  record.dynamicDependencies = dynamicDependencies;
}

function createProgram(snapshot, entryModules, isolateEntryFailures = false) {
  for (const record of snapshot.records.values()) {
    record.sourceFile = ts.createSourceFile(virtualName(record.logicalPath), record.source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS);
  }
  const activePaths = new Set();
  const validatedPaths = new Set();
  const rejectedPaths = new Map();
  const entryRejections = [];
  if (!isolateEntryFailures) {
    const pending = [...entryModules];
    while (pending.length > 0) {
      const logicalPath = pending.shift();
      if (activePaths.has(logicalPath)) continue;
      const record = snapshot.records.get(logicalPath);
      if (!record) throw new Rejection("source_changed", logicalPath);
      validateModuleSyntax(record, snapshot);
      activePaths.add(logicalPath);
      for (const imported of record.imports) pending.push(imported.logical_path);
    }
  } else {
    for (const entryModule of entryModules) {
      const closurePaths = new Set();
      const pending = [entryModule];
      try {
        while (pending.length > 0) {
          const logicalPath = pending.shift();
          if (activePaths.has(logicalPath) || closurePaths.has(logicalPath)) continue;
          const record = snapshot.records.get(logicalPath);
          if (!record) throw new Rejection("source_changed", logicalPath);
          if (rejectedPaths.has(logicalPath)) {
            throw new Rejection(rejectedPaths.get(logicalPath), logicalPath);
          }
          if (!validatedPaths.has(logicalPath)) {
            try {
              validateModuleSyntax(record, snapshot);
            } catch (error) {
              if (error instanceof Rejection) {
                rejectedPaths.set(logicalPath, safeRejection(error).error_code);
              }
              throw error;
            }
            validatedPaths.add(logicalPath);
          }
          closurePaths.add(logicalPath);
          for (const imported of record.imports) pending.push(imported.logical_path);
        }
      } catch (error) {
        if (!(error instanceof Rejection)) throw error;
        const rejection = safeRejection(error);
        if (rejection.error_code === "unclassified_internal_result") throw error;
        entryRejections.push(rejection.error_code);
        continue;
      }
      for (const logicalPath of closurePaths) activePaths.add(logicalPath);
    }
  }
  const intrinsicSource = [
    "interface __ReweaveMath {",
    "  min(...values: number[]): number;",
    "  max(...values: number[]): number;",
    "  abs(value: number): number;",
    "}",
    "declare const Math: __ReweaveMath;",
  ].join("\n");
  const intrinsicFile = ts.createSourceFile(INTRINSIC_PATH, intrinsicSource, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS);
  const options = {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Node10,
    allowJs: true,
    checkJs: true,
    noLib: true,
    noResolve: false,
    skipLibCheck: true,
    strict: true,
  };
  const host = {
    getSourceFile(fileName) {
      if (fileName === INTRINSIC_PATH) return intrinsicFile;
      const logical = logicalFromVirtual(fileName);
      return logical ? snapshot.records.get(logical)?.sourceFile : undefined;
    },
    getDefaultLibFileName: () => INTRINSIC_PATH,
    writeFile: () => {},
    getCurrentDirectory: () => VIRTUAL_ROOT,
    getDirectories: () => [],
    fileExists(fileName) {
      if (fileName === INTRINSIC_PATH) return true;
      const logical = logicalFromVirtual(fileName);
      return Boolean(logical && snapshot.records.has(logical));
    },
    readFile(fileName) {
      if (fileName === INTRINSIC_PATH) return intrinsicSource;
      const logical = logicalFromVirtual(fileName);
      return logical ? snapshot.records.get(logical)?.source : undefined;
    },
    getCanonicalFileName: (fileName) => fileName,
    useCaseSensitiveFileNames: () => true,
    getNewLine: () => "\n",
    realpath: (fileName) => fileName,
    resolveModuleNames(moduleNames, containingFile) {
      const from = logicalFromVirtual(containingFile);
      if (!from) return moduleNames.map(() => undefined);
      return moduleNames.map((specifier) => {
        try {
          const logical = resolveSpecifier(snapshot, from, specifier);
          return {
            resolvedFileName: virtualName(logical),
            extension: logical.endsWith(".mjs") ? ts.Extension.Mjs : ts.Extension.Js,
            isExternalLibraryImport: false,
          };
        } catch {
          return undefined;
        }
      });
    },
  };
  const rootNames = [INTRINSIC_PATH, ...[...activePaths].sort(compareUtf8).map(virtualName)];
  const program = ts.createProgram({ rootNames, options, host });
  return { program, checker: program.getTypeChecker(), intrinsicFile, activePaths, entryRejections };
}

function createGraph(snapshot, programState) {
  const { checker, intrinsicFile } = programState;
  const descriptorBySymbol = new Map();
  const descriptorByNode = new Map();
  const descriptorsByPath = new Map([...programState.activePaths].map((logicalPath) => [logicalPath, []]));

  function resolvedSymbol(symbol) {
    let current = symbol;
    const seen = new Set();
    while (current && (current.flags & ts.SymbolFlags.Alias) !== 0) {
      if (seen.has(current)) throw new Rejection("closure_unproven");
      seen.add(current);
      current = checker.getAliasedSymbol(current);
    }
    return current;
  }

  function symbolForName(name) {
    return name ? resolvedSymbol(checker.getSymbolAtLocation(name)) : null;
  }

  function kindForVariable(node) {
    const list = node.parent;
    const moduleLevel = !containingFunction(node);
    if (list.flags & ts.NodeFlags.Const) return moduleLevel ? "module_const" : "local_const";
    return moduleLevel ? "module_mutable" : "local_mutable";
  }

  function ensureDescriptor(node, explicitKind = null, ordinal = null) {
    if (descriptorByNode.has(node)) return descriptorByNode.get(node);
    const sourceFile = node.getSourceFile();
    const logicalPath = logicalFromVirtual(sourceFile.fileName);
    if (!logicalPath) return null;
    const record = snapshot.records.get(logicalPath);
    let nameNode = declarationNameNode(node);
    if (!nameNode && (ts.isFunctionExpression(node) || ts.isArrowFunction(node)) &&
        ts.isVariableDeclaration(node.parent) && ts.isIdentifier(node.parent.name)) {
      nameNode = node.parent.name;
    }
    let symbol = symbolForName(nameNode);
    if (!symbol && ts.isFunctionLike(node)) {
      const moduleSymbol = checker.getSymbolAtLocation(sourceFile) || sourceFile.symbol;
      if (moduleSymbol) {
        const match = checker.getExportsOfModule(moduleSymbol)
          .map((exported) => resolvedSymbol(exported))
          .find((exported) => exported?.declarations?.includes(node));
        symbol = match || null;
      }
    }
    if (!symbol) return null;
    const parentFunction = containingFunction(node);
    const parentDescriptor = parentFunction ? ensureDescriptor(parentFunction) : null;
    const [startUtf16, endUtf16] = bindingDeclarationSpan(node, sourceFile);
    const startByte = byteOffset(record, startUtf16);
    const endByte = byteOffset(record, endUtf16);
    const declarationSha256 = sha256Bytes(record.bytes.subarray(startByte, endByte));
    let kind = explicitKind;
    if (!kind && ts.isFunctionLike(node)) kind = "function";
    if (!kind && ts.isParameter(node)) kind = "parameter";
    if (!kind && ts.isVariableDeclaration(node)) kind = kindForVariable(node);
    if (!kind) return null;
    const identity = {
      source_graph_version: SOURCE_GRAPH_VERSION,
      logical_path: logicalPath,
      binding_kind: kind,
      start_byte: startByte,
      end_byte: endByte,
      declaration_sha256: declarationSha256,
      lexical_parent_binding_id: parentDescriptor?.binding_id || null,
    };
    if (ordinal !== null) identity.ordinal = ordinal;
    const position = sourceFile.getLineAndCharacterOfPosition(startUtf16);
    const descriptor = {
      binding_id: canonicalSha256(identity),
      kind,
      display_name: nameNode?.text || null,
      lexical_parent_binding_id: parentDescriptor?.binding_id || null,
      start_utf16: startUtf16,
      end_utf16: endUtf16,
      start_byte: startByte,
      end_byte: endByte,
      line: position.line + 1,
      column: position.character + 1,
      declaration_sha256: declarationSha256,
      calls: [],
      reads: [],
      writes: [],
      captures: [],
    };
    if (ts.isFunctionLike(node)) descriptor.parameters = [];
    descriptorByNode.set(node, descriptor);
    descriptorBySymbol.set(symbol, descriptor);
    descriptorsByPath.get(logicalPath).push(descriptor);
    if (ts.isFunctionLike(node)) {
      node.parameters.forEach((parameter, index) => {
        if (!ts.isIdentifier(parameter.name)) return;
        const item = ensureDescriptor(parameter, "parameter", index);
        if (item) descriptor.parameters.push({ binding_id: item.binding_id, display_name: item.display_name });
      });
    }
    return descriptor;
  }

  function discover(node) {
    if (ts.isFunctionDeclaration(node)) ensureDescriptor(node);
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
      if (node.initializer && (ts.isFunctionExpression(node.initializer) || ts.isArrowFunction(node.initializer))) {
        ensureDescriptor(node.initializer);
        const symbol = symbolForName(node.name);
        const descriptor = descriptorByNode.get(node.initializer);
        if (symbol && descriptor) {
          descriptor.display_name = node.name.text;
          descriptorBySymbol.set(symbol, descriptor);
        }
      } else {
        ensureDescriptor(node);
      }
    }
    if (ts.isFunctionExpression(node) || ts.isArrowFunction(node)) {
      if (!ts.isVariableDeclaration(node.parent)) ensureDescriptor(node);
    }
    ts.forEachChild(node, discover);
  }
  for (const logicalPath of programState.activePaths) discover(snapshot.records.get(logicalPath).sourceFile);

  const exportAliasByKey = new Map();

  function addAliasDescriptor(node, nameNode, kind, targetSymbol, aliasSymbol = null) {
    const logicalPath = logicalFromVirtual(node.getSourceFile().fileName);
    const record = logicalPath ? snapshot.records.get(logicalPath) : null;
    const target = descriptorBySymbol.get(targetSymbol) || descriptorBySymbol.get(resolvedSymbol(targetSymbol));
    if (!record || !target) return null;
    const startUtf16 = node.getStart(node.getSourceFile(), false);
    const endUtf16 = node.end;
    const startByte = byteOffset(record, startUtf16);
    const endByte = byteOffset(record, endUtf16);
    const declarationSha256 = sha256Bytes(record.bytes.subarray(startByte, endByte));
    const tokenStart = byteOffset(record, nameNode.getStart(node.getSourceFile(), false));
    const tokenEnd = byteOffset(record, nameNode.end);
    const exportTokenSha256 = sha256Bytes(record.bytes.subarray(tokenStart, tokenEnd));
    const identity = {
      source_graph_version: SOURCE_GRAPH_VERSION,
      logical_path: logicalPath,
      binding_kind: kind,
      start_byte: startByte,
      end_byte: endByte,
      declaration_sha256: declarationSha256,
      lexical_parent_binding_id: null,
      target_binding_id: target.binding_id,
      export_token_sha256: exportTokenSha256,
    };
    const position = node.getSourceFile().getLineAndCharacterOfPosition(startUtf16);
    const descriptor = {
      binding_id: canonicalSha256(identity),
      kind,
      display_name: nameNode.text,
      lexical_parent_binding_id: null,
      target_binding_id: target.binding_id,
      export_token_sha256: exportTokenSha256,
      start_utf16: startUtf16,
      end_utf16: endUtf16,
      start_byte: startByte,
      end_byte: endByte,
      line: position.line + 1,
      column: position.character + 1,
      declaration_sha256: declarationSha256,
      calls: [],
      reads: [target.binding_id],
      writes: [],
      captures: [],
    };
    descriptorByNode.set(node, descriptor);
    if (aliasSymbol) descriptorBySymbol.set(aliasSymbol, descriptor);
    descriptorsByPath.get(logicalPath).push(descriptor);
    return descriptor;
  }

  for (const logicalPath of programState.activePaths) {
    const record = snapshot.records.get(logicalPath);
    for (const statement of record.sourceFile.statements) {
      if (ts.isImportDeclaration(statement) && statement.importClause) {
        const importedBindings = [];
        const names = [];
        if (statement.importClause.name) names.push([statement.importClause, statement.importClause.name]);
        if (statement.importClause.namedBindings && ts.isNamedImports(statement.importClause.namedBindings)) {
          for (const element of statement.importClause.namedBindings.elements) names.push([element, element.name]);
        }
        for (const [node, nameNode] of names) {
          const rawSymbol = checker.getSymbolAtLocation(nameNode);
          const descriptor = rawSymbol
            ? addAliasDescriptor(node, nameNode, "import_alias", rawSymbol, rawSymbol)
            : null;
          if (descriptor) importedBindings.push(descriptor.binding_id);
        }
        const imported = record.imports.find((item) => item.specifier === statement.moduleSpecifier.text && !item.reexport);
        if (imported) imported.binding_ids = importedBindings.sort();
      }
      if (ts.isExportDeclaration(statement) && statement.exportClause && ts.isNamedExports(statement.exportClause)) {
        for (const element of statement.exportClause.elements) {
          const aliasSymbol = checker.getSymbolAtLocation(element.name);
          const targetSymbol = checker.getSymbolAtLocation(element.propertyName || element.name);
          const descriptor = aliasSymbol && targetSymbol
            ? addAliasDescriptor(element, element.name, "export_alias", targetSymbol, aliasSymbol)
            : null;
          if (descriptor) exportAliasByKey.set(`${logicalPath}\u0000${element.name.text}`, descriptor);
        }
      }
      if (ts.isExportAssignment(statement) && !statement.isExportEquals && ts.isIdentifier(statement.expression)) {
        const rawSymbol = checker.getSymbolAtLocation(statement.expression);
        const descriptor = rawSymbol
          ? addAliasDescriptor(statement, statement.expression, "export_alias", rawSymbol)
          : null;
        if (descriptor) exportAliasByKey.set(`${logicalPath}\u0000default`, descriptor);
      }
    }
  }

  function lexicalDescriptorAt(identifier) {
    const rawSymbol = checker.getSymbolAtLocation(identifier);
    if (!rawSymbol) return null;
    return descriptorBySymbol.get(rawSymbol) || descriptorBySymbol.get(resolvedSymbol(rawSymbol)) || null;
  }

  function semanticLeafDescriptorAt(identifier) {
    const rawSymbol = checker.getSymbolAtLocation(identifier);
    return rawSymbol ? descriptorBySymbol.get(resolvedSymbol(rawSymbol)) || null : null;
  }

  function analyzeFunction(node) {
    const descriptor = descriptorByNode.get(node);
    if (!descriptor) return;
    const calls = new Set();
    const reads = new Set();
    const writes = new Set();
    const captures = new Set();
    function visit(current, root = false) {
      if (!root && ts.isFunctionLike(current)) return;
      if (ts.isCallExpression(current) && ts.isIdentifier(current.expression)) {
        const target = lexicalDescriptorAt(current.expression);
        if (target) calls.add(target.binding_id);
      }
      if (ts.isIdentifier(current) && !isDeclarationIdentifier(current)) {
        const target = lexicalDescriptorAt(current);
        if (target) {
          if (isWriteIdentifier(current)) writes.add(target.binding_id);
          else reads.add(target.binding_id);
          if (target.lexical_parent_binding_id !== descriptor.binding_id && target.binding_id !== descriptor.binding_id) {
            captures.add(target.binding_id);
          }
        }
      }
      ts.forEachChild(current, (child) => visit(child, false));
    }
    visit(node, true);
    descriptor.calls = [...calls].sort();
    descriptor.reads = [...reads].sort();
    descriptor.writes = [...writes].sort();
    descriptor.captures = [...captures].sort();
  }
  for (const [node] of descriptorByNode) if (ts.isFunctionLike(node)) analyzeFunction(node);

  const mathDeclaration = intrinsicFile.statements.at(-1).declarationList.declarations[0];
  const mathSymbol = checker.getSymbolAtLocation(mathDeclaration.name);

  function moduleDynamicDependencies(sourceFile) {
    const evidence = new Map();
    function add(kind, node) {
      const key = `${kind}:${node.getStart(sourceFile, false)}`;
      evidence.set(key, { kind, start_utf16: node.getStart(sourceFile, false) });
    }
    function visit(node) {
      if (ts.isCallExpression(node)) {
        if (node.expression.kind === ts.SyntaxKind.ImportKeyword) {
          add("dynamic_import", node);
        } else if (ts.isIdentifier(node.expression)) {
          const target = semanticLeafDescriptorAt(node.expression);
          if (!target || target.kind !== "function") add("unknown_call", node);
        } else if (ts.isPropertyAccessExpression(node.expression)) {
          const receiver = node.expression.expression;
          const receiverSymbol = ts.isIdentifier(receiver)
            ? resolvedSymbol(checker.getSymbolAtLocation(receiver))
            : null;
          const allowedMath = receiverSymbol === resolvedSymbol(mathSymbol) &&
            ["min", "max", "abs"].includes(node.expression.name.text);
          if (!allowedMath) add("unknown_member_call", node);
        } else {
          add("unknown_call", node);
        }
      }
      if (ts.isElementAccessExpression(node)) add("unknown_element_access", node);
      if (ts.isPropertyAccessExpression(node) && !ts.isCallExpression(node.parent)) {
        add("unknown_property_read", node);
      }
      if (ts.isIdentifier(node) && !isDeclarationIdentifier(node)) {
        const symbol = checker.getSymbolAtLocation(node);
        const resolved = resolvedSymbol(symbol);
        const intrinsic = resolved === resolvedSymbol(mathSymbol);
        const declarations = resolved?.declarations || [];
        if (!intrinsic && (!resolved || declarations.length === 0 ||
            declarations.every((item) => item.getSourceFile?.().isDeclarationFile))) {
          add("unknown_read", node);
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(sourceFile);
    return [...evidence.values()].sort((a, b) => a.start_utf16 - b.start_utf16 || a.kind.localeCompare(b.kind));
  }

  function topLevelNeedsEvidence(statement) {
    if (ts.isImportDeclaration(statement) || ts.isExportDeclaration(statement) || ts.isFunctionDeclaration(statement)) {
      return false;
    }
    if (ts.isExportAssignment(statement) && !statement.isExportEquals && ts.isIdentifier(statement.expression)) {
      return false;
    }
    if (!ts.isVariableStatement(statement) || (statement.declarationList.flags & ts.NodeFlags.Const) === 0) {
      return !ts.isEmptyStatement(statement);
    }
    function isStaticScalar(node) {
      if (ts.isNumericLiteral(node)) {
        const value = Number(node.text);
        return Number.isSafeInteger(value) ? { kind: "integer", value } : null;
      }
      if (ts.isStringLiteral(node)) return { kind: "enum", value: node.text };
      if (node.kind === ts.SyntaxKind.TrueKeyword) return { kind: "boolean", value: true };
      if (node.kind === ts.SyntaxKind.FalseKeyword) return { kind: "boolean", value: false };
      if (ts.isParenthesizedExpression(node)) return isStaticScalar(node.expression);
      if (ts.isPrefixUnaryExpression(node)) {
        const operand = isStaticScalar(node.operand);
        if (!operand) return null;
        if (node.operator === ts.SyntaxKind.ExclamationToken && operand.kind === "boolean") {
          return { kind: "boolean", value: !operand.value };
        }
        if ([ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken].includes(node.operator) &&
            operand.kind === "integer") {
          const value = node.operator === ts.SyntaxKind.MinusToken ? -operand.value : operand.value;
          return Number.isSafeInteger(value) ? { kind: "integer", value } : null;
        }
      }
      return null;
    }
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || !declaration.initializer) return true;
      if (ts.isFunctionExpression(declaration.initializer) || ts.isArrowFunction(declaration.initializer)) continue;
      if (isStaticScalar(declaration.initializer) === null) return true;
    }
    return false;
  }

  const modules = [];
  const activeRecords = [...programState.activePaths]
    .map((logicalPath) => snapshot.records.get(logicalPath))
    .sort((a, b) => compareUtf8(a.logicalPath, b.logicalPath));
  for (const record of activeRecords) {
    const sourceFile = record.sourceFile;
    const moduleSymbol = checker.getSymbolAtLocation(sourceFile) || sourceFile.symbol;
    const exports = [];
    if (moduleSymbol) {
      for (const exported of checker.getExportsOfModule(moduleSymbol)) {
        const publicName = exported.getName();
        if (publicName !== "default" && !ts.isIdentifierText(publicName, ts.ScriptTarget.ES2022, ts.LanguageVariant.Standard)) {
          throw new Rejection("invalid_export_identifier", record.logicalPath);
        }
        const leaf = resolvedSymbol(exported);
        const descriptor = exportAliasByKey.get(`${record.logicalPath}\u0000${publicName}`) || descriptorBySymbol.get(leaf);
        if (descriptor) exports.push({ public_name: publicName, binding_id: descriptor.binding_id });
      }
    }
    const topLevelExecution = [];
    for (const statement of sourceFile.statements) {
      if (topLevelNeedsEvidence(statement)) {
        topLevelExecution.push({ kind: syntaxKindName(statement), start_utf16: statement.getStart(sourceFile, false) });
      }
    }
    modules.push({
      logical_path: record.logicalPath,
      sha256: record.sha256,
      imports: record.imports,
      exports: exports.sort((a, b) => compareUtf8(a.public_name, b.public_name)),
      bindings: descriptorsByPath.get(record.logicalPath).sort((a, b) => a.start_byte - b.start_byte || a.binding_id.localeCompare(b.binding_id)),
      top_level_execution: topLevelExecution,
      dynamic_dependencies: moduleDynamicDependencies(sourceFile),
    });
  }
  return {
    modules,
    checker,
    descriptorBySymbol,
    descriptorByNode,
    resolvedSymbol,
    mathSymbol,
  };
}

/*
 * Stage D proof/DSL fragment.
 *
 * This file deliberately has no filesystem or process access.  The caller owns
 * the frozen TypeScript Program and the snapshot-only module resolver.
 *
 * Required graphContext surface:
 *   sourceFileByLogicalPath(path) -> ts.SourceFile | undefined
 *   logicalPathOfSourceFile(sourceFile) -> string
 *   resolveModule(fromLogicalPath, specifier) ->
 *       { logicalPath, sourceFile, viaSymlink?: boolean } | undefined
 *   bindingIdForSymbol(symbol) -> string
 *   sha256ForSourceFile(sourceFile) -> lowercase SHA-256 of snapshot bytes
 *
 * Optional:
 *   intrinsicMathSymbol or isIntrinsicMathSymbol(symbol) -> boolean
 *   maxModules (32), maxImportDepth (8), maxClosureBytes (4 MiB)
 *
 * Rejection is expected to accept (errorCode, logicalPath?).
 */

const MIN_SAFE = Number.MIN_SAFE_INTEGER;
const MAX_INT_SEGMENTS = 16;
const MAX_ENUM_VALUES = 32;
const MAX_SWITCH_CASES = 16;

function installProof({ ts, checker, graphContext, Rejection, canonicalSha256 }) {
  if (!ts || !checker || !graphContext || !Rejection || !canonicalSha256) {
    throw new TypeError("installProof dependencies are required");
  }

  const textEncoder = new TextEncoder();

  function reject(code, nodeOrPath = null) {
    let logicalPath = null;
    if (typeof nodeOrPath === "string") logicalPath = nodeOrPath;
    else if (nodeOrPath?.getSourceFile) {
      logicalPath = graphContext.logicalPathOfSourceFile(nodeOrPath.getSourceFile());
    }
    throw new Rejection(code, logicalPath);
  }

  function compareUtf8(left, right) {
    const a = textEncoder.encode(left);
    const b = textEncoder.encode(right);
    const length = Math.min(a.length, b.length);
    for (let index = 0; index < length; index += 1) {
      if (a[index] !== b[index]) return a[index] - b[index];
    }
    return a.length - b.length;
  }

  function resolveAlias(symbol, node = null) {
    let current = symbol;
    const seen = new Set();
    while (current && (current.flags & ts.SymbolFlags.Alias) !== 0) {
      if (seen.has(current)) reject("closure_unproven", node);
      seen.add(current);
      current = checker.getAliasedSymbol(current);
    }
    if (!current) reject("closure_unproven", node);
    return current;
  }

  function symbolAt(node, { resolve = true } = {}) {
    const symbol = checker.getSymbolAtLocation(node);
    if (!symbol) reject("closure_unproven", node);
    return resolve ? resolveAlias(symbol, node) : symbol;
  }

  function bindingId(symbol, node = null) {
    const resolved = resolveAlias(symbol, node);
    const value = graphContext.bindingIdForSymbol(resolved);
    if (typeof value !== "string" || value.length === 0) reject("closure_unproven", node);
    return value;
  }

  function snapshotSha256(sourceFile) {
    const value = graphContext.sha256ForSourceFile?.(sourceFile);
    if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
      reject("closure_unproven", graphContext.logicalPathOfSourceFile(sourceFile));
    }
    return value;
  }

  function declarationForSymbol(symbol, node = null) {
    const resolved = resolveAlias(symbol, node);
    const declarations = (resolved.declarations || []).filter((declaration) => {
      const sourceFile = declaration.getSourceFile?.();
      return sourceFile && !sourceFile.isDeclarationFile;
    });
    if (declarations.length !== 1) reject("closure_unproven", node);
    return declarations[0];
  }

  function functionNodeForSymbol(symbol, node = null) {
    const declaration = declarationForSymbol(symbol, node);
    if (ts.isFunctionDeclaration(declaration)) {
      if (!declaration.body) reject("closure_unproven", declaration);
      return declaration;
    }
    if (ts.isVariableDeclaration(declaration) && declaration.initializer &&
        (ts.isFunctionExpression(declaration.initializer) || ts.isArrowFunction(declaration.initializer))) {
      return declaration.initializer;
    }
    if (ts.isFunctionExpression(declaration) || ts.isArrowFunction(declaration)) return declaration;
    reject("closure_unproven", declaration);
  }

  function variableDeclarationForSymbol(symbol, node = null) {
    const declaration = declarationForSymbol(symbol, node);
    if (!ts.isVariableDeclaration(declaration) || !ts.isIdentifier(declaration.name)) {
      reject("closure_unproven", declaration);
    }
    return declaration;
  }

  function isConstDeclaration(declaration) {
    const list = declaration.parent;
    return ts.isVariableDeclarationList(list) && (list.flags & ts.NodeFlags.Const) !== 0;
  }

  function isLetDeclaration(declaration) {
    const list = declaration.parent;
    return ts.isVariableDeclarationList(list) && (list.flags & ts.NodeFlags.Let) !== 0;
  }

  function intrinsicMath(symbol) {
    const resolved = resolveAlias(symbol);
    if (typeof graphContext.isIntrinsicMathSymbol === "function") {
      return graphContext.isIntrinsicMathSymbol(resolved) === true;
    }
    return graphContext.intrinsicMathSymbol != null && resolved === graphContext.intrinsicMathSymbol;
  }

  function bottom() {
    return Object.freeze({ kind: "bottom" });
  }

  function boolSet(values) {
    const unique = [...new Set(values)].sort();
    if (unique.length === 0) return bottom();
    return Object.freeze({ kind: "boolean", values: Object.freeze(unique) });
  }

  function enumSet(values, node = null) {
    const unique = [...new Set(values)];
    if (unique.length === 0) return bottom();
    if (unique.length > MAX_ENUM_VALUES) reject("interval_unproven", node);
    unique.sort(compareUtf8);
    return Object.freeze({ kind: "enum", values: Object.freeze(unique) });
  }

  function assertSafeInteger(value, node = null) {
    if (!Number.isSafeInteger(value)) reject("interval_unproven", node);
    return Object.is(value, -0) ? 0 : value;
  }

  function normalizeIntervals(intervals, node = null) {
    if (!Array.isArray(intervals) || intervals.length === 0) return bottom();
    const sorted = intervals.map(([minimum, maximum]) => {
      minimum = assertSafeInteger(minimum, node);
      maximum = assertSafeInteger(maximum, node);
      if (minimum > maximum) reject("interval_unproven", node);
      return [minimum, maximum];
    }).sort((left, right) => left[0] - right[0] || left[1] - right[1]);
    const merged = [];
    for (const [minimum, maximum] of sorted) {
      const previous = merged.at(-1);
      if (previous && (minimum <= previous[1] ||
          (previous[1] < MAX_SAFE && minimum === previous[1] + 1))) {
        previous[1] = Math.max(previous[1], maximum);
      } else {
        merged.push([minimum, maximum]);
      }
    }
    if (merged.length > MAX_INT_SEGMENTS) reject("interval_unproven", node);
    return Object.freeze({
      kind: "integer",
      intervals: Object.freeze(merged.map((pair) => Object.freeze(pair))),
    });
  }

  function intSet(intervals, node = null) {
    return normalizeIntervals(intervals, node);
  }

  function singleton(domain) {
    if (domain.kind === "integer" && domain.intervals.length === 1 &&
        domain.intervals[0][0] === domain.intervals[0][1]) return domain.intervals[0][0];
    if (domain.kind === "boolean" && domain.values.length === 1) return domain.values[0];
    if (domain.kind === "enum" && domain.values.length === 1) return domain.values[0];
    return undefined;
  }

  function serializeDomain(domain) {
    if (domain.kind === "bottom") return { kind: "bottom" };
    if (domain.kind === "integer") {
      return { kind: "integer", intervals: domain.intervals.map((pair) => [...pair]) };
    }
    return { kind: domain.kind, values: [...domain.values] };
  }

  function sameDomainKind(left, right, node = null) {
    if (left.kind !== right.kind || left.kind === "bottom") reject("interval_unproven", node);
  }

  function unionDomains(domains, node = null) {
    const live = domains.filter((domain) => domain.kind !== "bottom");
    if (live.length === 0) return bottom();
    const kind = live[0].kind;
    if (live.some((domain) => domain.kind !== kind)) reject("interval_unproven", node);
    if (kind === "integer") return intSet(live.flatMap((domain) => domain.intervals), node);
    if (kind === "boolean") return boolSet(live.flatMap((domain) => domain.values));
    if (kind === "enum") return enumSet(live.flatMap((domain) => domain.values), node);
    reject("interval_unproven", node);
  }

  function cartesianInteger(left, right, transfer, node) {
    sameDomainKind(left, right, node);
    if (left.kind !== "integer") reject("interval_unproven", node);
    const result = [];
    for (const leftInterval of left.intervals) {
      for (const rightInterval of right.intervals) {
        result.push(...transfer(leftInterval, rightInterval));
      }
    }
    return intSet(result, node);
  }

  function add(left, right, node) {
    return cartesianInteger(left, right, ([a, b], [c, d]) => [
      [assertSafeInteger(a + c, node), assertSafeInteger(b + d, node)],
    ], node);
  }

  function subtract(left, right, node) {
    return cartesianInteger(left, right, ([a, b], [c, d]) => [
      [assertSafeInteger(a - d, node), assertSafeInteger(b - c, node)],
    ], node);
  }

  function multiply(left, right, node) {
    return cartesianInteger(left, right, ([a, b], [c, d]) => {
      const products = [a * c, a * d, b * c, b * d].map((value) => assertSafeInteger(value, node));
      return [[Math.min(...products), Math.max(...products)]];
    }, node);
  }

  function remainder(left, right, node) {
    return cartesianInteger(left, right, ([minimum, maximum], [divisorMin, divisorMax]) => {
      if (divisorMin <= 0 && divisorMax >= 0) reject("interval_unproven", node);
      const limit = Math.max(Math.abs(divisorMin), Math.abs(divisorMax)) - 1;
      assertSafeInteger(limit, node);
      const result = [];
      if (maximum >= 0) result.push([0, Math.min(Math.max(0, maximum), limit)]);
      if (minimum < 0) result.push([-Math.min(Math.abs(minimum), limit), 0]);
      return result;
    }, node);
  }

  function negate(domain, node) {
    if (domain.kind !== "integer") reject("interval_unproven", node);
    return intSet(domain.intervals.map(([minimum, maximum]) => [
      assertSafeInteger(-maximum, node),
      assertSafeInteger(-minimum, node),
    ]), node);
  }

  function mathAbs(domain, node) {
    if (domain.kind !== "integer") reject("interval_unproven", node);
    return intSet(domain.intervals.map(([minimum, maximum]) => {
      if (minimum <= 0 && maximum >= 0) {
        return [0, assertSafeInteger(Math.max(Math.abs(minimum), Math.abs(maximum)), node)];
      }
      const values = [assertSafeInteger(Math.abs(minimum), node), assertSafeInteger(Math.abs(maximum), node)];
      return [Math.min(...values), Math.max(...values)];
    }), node);
  }

  function mathMinMax(domains, mode, node) {
    if (domains.length === 0 || domains.some((domain) => domain.kind !== "integer")) {
      reject("interval_unproven", node);
    }
    const combinations = [[]];
    for (const domain of domains) {
      const next = [];
      for (const combination of combinations) {
        for (const interval of domain.intervals) next.push([...combination, interval]);
      }
      combinations.splice(0, combinations.length, ...next);
      if (combinations.length > 4096) reject("interval_unproven", node);
    }
    return intSet(combinations.map((combination) => {
      const lows = combination.map(([minimum]) => minimum);
      const highs = combination.map(([, maximum]) => maximum);
      return mode === "min"
        ? [Math.min(...lows), Math.min(...highs)]
        : [Math.max(...lows), Math.max(...highs)];
    }), node);
  }

  function compareDomains(left, right, operator, node) {
    if (["<", "<=", ">", ">="].includes(operator)) {
      if (left.kind !== "integer" || right.kind !== "integer") reject("interval_unproven", node);
      let canTrue = false;
      let canFalse = false;
      for (const [a, b] of left.intervals) {
        for (const [c, d] of right.intervals) {
          if (operator === "<") {
            canTrue ||= a < d;
            canFalse ||= b >= c;
          } else if (operator === "<=") {
            canTrue ||= a <= d;
            canFalse ||= b > c;
          } else if (operator === ">") {
            canTrue ||= b > c;
            canFalse ||= a <= d;
          } else {
            canTrue ||= b >= c;
            canFalse ||= a < d;
          }
        }
      }
      return boolSet([...(canFalse ? [false] : []), ...(canTrue ? [true] : [])]);
    }
    if (operator !== "===" && operator !== "!==") reject("unsupported_control_flow", node);
    sameDomainKind(left, right, node);
    let overlap = false;
    let identicalSingleton = false;
    if (left.kind === "integer") {
      overlap = left.intervals.some(([a, b]) => right.intervals.some(([c, d]) => a <= d && c <= b));
      identicalSingleton = singleton(left) !== undefined && singleton(left) === singleton(right);
    } else {
      overlap = left.values.some((value) => right.values.includes(value));
      identicalSingleton = left.values.length === 1 && right.values.length === 1 && left.values[0] === right.values[0];
    }
    const equal = boolSet([...(identicalSingleton ? [] : [false]), ...(overlap ? [true] : [])]);
    return operator === "===" ? equal : boolSet(equal.values.map((value) => !value));
  }

  function complementBoolean(domain, node) {
    if (domain.kind !== "boolean") reject("interval_unproven", node);
    return boolSet(domain.values.map((value) => !value));
  }

  function parseParameterDomain(raw, node = null) {
    if (!raw || typeof raw !== "object") reject("interval_unproven", node);
    if (raw.kind === "integer") {
      const domain = intSet(raw.intervals, node);
      if (domain.kind === "bottom") reject("interval_unproven", node);
      return domain;
    }
    if (raw.kind === "boolean") {
      if (!Array.isArray(raw.values) || raw.values.length === 0 ||
          raw.values.some((value) => typeof value !== "boolean")) {
        reject("interval_unproven", node);
      }
      return boolSet(raw.values);
    }
    if (raw.kind === "enum") {
      if (!Array.isArray(raw.values) || raw.values.length === 0 ||
          raw.values.some((value) => typeof value !== "string")) {
        reject("interval_unproven", node);
      }
      return enumSet(raw.values, node);
    }
    reject("interval_unproven", node);
  }

  function parseIntegerLiteral(node) {
    const raw = node.getText().replaceAll("_", "");
    const isIntegerToken = /^(?:0|[1-9][0-9]*|0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+)$/.test(raw);
    if (!isIntegerToken) reject("interval_unproven", node);
    return assertSafeInteger(Number(raw), node);
  }

  function literalDomain(node) {
    if (ts.isNumericLiteral(node)) {
      const value = parseIntegerLiteral(node);
      return intSet([[value, value]], node);
    }
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      return enumSet([node.text], node);
    }
    if (node.kind === ts.SyntaxKind.TrueKeyword) return boolSet([true]);
    if (node.kind === ts.SyntaxKind.FalseKeyword) return boolSet([false]);
    return null;
  }

  function operatorText(kind) {
    const map = new Map([
      [ts.SyntaxKind.PlusToken, "+"],
      [ts.SyntaxKind.MinusToken, "-"],
      [ts.SyntaxKind.AsteriskToken, "*"],
      [ts.SyntaxKind.PercentToken, "%"],
      [ts.SyntaxKind.LessThanToken, "<"],
      [ts.SyntaxKind.LessThanEqualsToken, "<="],
      [ts.SyntaxKind.GreaterThanToken, ">"],
      [ts.SyntaxKind.GreaterThanEqualsToken, ">="],
      [ts.SyntaxKind.EqualsEqualsEqualsToken, "==="],
      [ts.SyntaxKind.ExclamationEqualsEqualsToken, "!=="],
      [ts.SyntaxKind.AmpersandAmpersandToken, "&&"],
      [ts.SyntaxKind.BarBarToken, "||"],
    ]);
    return map.get(kind) || null;
  }

  function moduleDependencyClosure(entrySourceFile) {
    const maxModules = graphContext.maxModules ?? 32;
    const maxDepth = graphContext.maxImportDepth ?? 8;
    const maxBytes = graphContext.maxClosureBytes ?? (4 * 1024 * 1024);
    const byPath = new Map();
    const active = new Set();
    let byteCount = 0;

    function visit(sourceFile, depth) {
      const logicalPath = graphContext.logicalPathOfSourceFile(sourceFile);
      if (depth > maxDepth) reject("closure_unproven", logicalPath);
      if (active.has(logicalPath)) reject("closure_unproven", logicalPath);
      if (byPath.has(logicalPath)) return;
      byPath.set(logicalPath, sourceFile);
      active.add(logicalPath);
      if (byPath.size > maxModules) reject("closure_unproven", logicalPath);
      byteCount += textEncoder.encode(sourceFile.text).length;
      if (byteCount > maxBytes) reject("closure_unproven", logicalPath);
      for (const statement of sourceFile.statements) {
        let specifier = null;
        if (ts.isImportDeclaration(statement) || ts.isExportDeclaration(statement)) {
          if (statement.moduleSpecifier) {
            if (!ts.isStringLiteral(statement.moduleSpecifier)) reject("dynamic_dependency", statement);
            specifier = statement.moduleSpecifier.text;
          }
        }
        if (specifier == null) continue;
        const resolved = graphContext.resolveModule(logicalPath, specifier);
        if (!resolved) reject("dynamic_dependency", statement);
        if (resolved.viaSymlink === true) reject("closure_symlink_forbidden", statement);
        visit(resolved.sourceFile, depth + 1);
      }
      active.delete(logicalPath);
    }

    visit(entrySourceFile, 0);
    return { modules: [...byPath.entries()].sort(([a], [b]) => compareUtf8(a, b)), byteCount };
  }

  function resolveTarget(moduleRelpath, exportName) {
    const sourceFile = graphContext.sourceFileByLogicalPath(moduleRelpath);
    if (!sourceFile) reject("closure_unproven", moduleRelpath);
    const moduleSymbol = checker.getSymbolAtLocation(sourceFile) || sourceFile.symbol;
    if (!moduleSymbol) reject("closure_unproven", moduleRelpath);
    const exported = checker.getExportsOfModule(moduleSymbol).filter((symbol) => symbol.getName() === exportName);
    if (exported.length !== 1) reject("closure_unproven", moduleRelpath);
    const leaf = resolveAlias(exported[0]);
    const functionNode = functionNodeForSymbol(leaf);
    return { sourceFile, leafSymbol: leaf, functionNode };
  }

  function ensureFunctionSignature(functionNode) {
    if (functionNode.asteriskToken || functionNode.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.AsyncKeyword)) {
      reject("unsupported_control_flow", functionNode);
    }
    for (const parameter of functionNode.parameters) {
      if (!ts.isIdentifier(parameter.name) || parameter.dotDotDotToken || parameter.initializer || parameter.questionToken) {
        reject("unsupported_control_flow", parameter);
      }
    }
  }

  function scanFunctionSyntax(functionNode, auditState = null) {
    const state = auditState || { active: new Set(), done: new Set() };
    if (state.active.has(functionNode)) reject("closure_unproven", functionNode);
    if (state.done.has(functionNode)) return;
    state.active.add(functionNode);
    ensureFunctionSignature(functionNode);
    const allowedStatements = new Set([
      ts.SyntaxKind.Block,
      ts.SyntaxKind.VariableStatement,
      ts.SyntaxKind.ReturnStatement,
      ts.SyntaxKind.IfStatement,
      ts.SyntaxKind.SwitchStatement,
      ts.SyntaxKind.CaseBlock,
      ts.SyntaxKind.CaseClause,
      ts.SyntaxKind.DefaultClause,
      ts.SyntaxKind.FunctionDeclaration,
      ts.SyntaxKind.EmptyStatement,
    ]);
    const forbidden = new Set([
      ts.SyntaxKind.ForStatement,
      ts.SyntaxKind.ForInStatement,
      ts.SyntaxKind.ForOfStatement,
      ts.SyntaxKind.WhileStatement,
      ts.SyntaxKind.DoStatement,
      ts.SyntaxKind.TryStatement,
      ts.SyntaxKind.ThrowStatement,
      ts.SyntaxKind.CatchClause,
      ts.SyntaxKind.WithStatement,
      ts.SyntaxKind.AwaitExpression,
      ts.SyntaxKind.YieldExpression,
      ts.SyntaxKind.NewExpression,
      ts.SyntaxKind.DeleteExpression,
      ts.SyntaxKind.TaggedTemplateExpression,
      ts.SyntaxKind.RegularExpressionLiteral,
      ts.SyntaxKind.ObjectLiteralExpression,
      ts.SyntaxKind.ArrayLiteralExpression,
      ts.SyntaxKind.ClassExpression,
      ts.SyntaxKind.FunctionExpression,
      ts.SyntaxKind.ArrowFunction,
      ts.SyntaxKind.ThisKeyword,
      ts.SyntaxKind.SuperKeyword,
      ts.SyntaxKind.BreakStatement,
      ts.SyntaxKind.ContinueStatement,
      ts.SyntaxKind.LabeledStatement,
    ]);

    function visit(node, isRoot = false) {
      if (!isRoot && ts.isFunctionDeclaration(node)) {
        scanFunctionSyntax(node, state);
        return;
      }
      if (!isRoot && (ts.isFunctionExpression(node) || ts.isArrowFunction(node))) {
        reject("unsupported_control_flow", node);
      }
      if (!(isRoot && (ts.isFunctionExpression(node) || ts.isArrowFunction(node))) && forbidden.has(node.kind)) {
        reject("unsupported_control_flow", node);
      }
      if (!isRoot && ts.isExpression(node)) {
        const allowedExpression = ts.isIdentifier(node) || ts.isNumericLiteral(node) ||
          ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ||
          node.kind === ts.SyntaxKind.TrueKeyword || node.kind === ts.SyntaxKind.FalseKeyword ||
          ts.isParenthesizedExpression(node) || ts.isPrefixUnaryExpression(node) ||
          ts.isBinaryExpression(node) || ts.isConditionalExpression(node) ||
          ts.isCallExpression(node) || ts.isPropertyAccessExpression(node);
        if (!allowedExpression) reject("unsupported_control_flow", node);
      }
      if (!isRoot && ts.isStatement(node) && !allowedStatements.has(node.kind)) {
        if (ts.isExpressionStatement(node) && ts.isCallExpression(node.expression) &&
            node.expression.expression.kind === ts.SyntaxKind.ImportKeyword) {
          reject("dynamic_dependency", node);
        }
        reject("unsupported_control_flow", node);
      }
      if (ts.isVariableStatement(node)) {
        const flags = node.declarationList.flags;
        if ((flags & (ts.NodeFlags.Const | ts.NodeFlags.Let)) === 0) reject("unsupported_control_flow", node);
        for (const declaration of node.declarationList.declarations) {
          if (!ts.isIdentifier(declaration.name) || !declaration.initializer) {
            reject("unsupported_control_flow", declaration);
          }
        }
      }
      if (ts.isBinaryExpression(node)) {
        const operator = operatorText(node.operatorToken.kind);
        if (!operator) reject("unsupported_control_flow", node);
      }
      if (ts.isPrefixUnaryExpression(node) && ![
        ts.SyntaxKind.PlusToken,
        ts.SyntaxKind.MinusToken,
        ts.SyntaxKind.ExclamationToken,
      ].includes(node.operator)) reject("unsupported_control_flow", node);
      if (ts.isPostfixUnaryExpression(node)) reject("unsupported_control_flow", node);
      if (ts.isCallExpression(node)) {
        if (node.questionDotToken || node.typeArguments?.length) reject("dynamic_dependency", node);
        if (ts.isIdentifier(node.expression)) {
          const called = symbolAt(node.expression);
          const declaration = declarationForSymbol(called, node.expression);
          const isFunction = ts.isFunctionDeclaration(declaration) ||
            (ts.isVariableDeclaration(declaration) && declaration.initializer != null &&
              (ts.isFunctionExpression(declaration.initializer) || ts.isArrowFunction(declaration.initializer)));
          if (!isFunction) reject("dynamic_dependency", node);
          scanFunctionSyntax(functionNodeForSymbol(called, node.expression), state);
        } else if (ts.isPropertyAccessExpression(node.expression)) {
          const receiver = node.expression.expression;
          if (!ts.isIdentifier(receiver) || !["min", "max", "abs"].includes(node.expression.name.text)) {
            reject("unsupported_control_flow", node);
          }
          const mathSymbol = symbolAt(receiver);
          if (!intrinsicMath(mathSymbol)) reject("unsupported_control_flow", node);
        } else {
          reject("dynamic_dependency", node);
        }
      }
      if (ts.isPropertyAccessExpression(node) && !ts.isCallExpression(node.parent)) {
        reject("unsupported_control_flow", node);
      }
      if (ts.isElementAccessExpression(node) || ts.isNonNullExpression(node) || ts.isAsExpression(node) ||
          ts.isTypeAssertionExpression(node) || ts.isTemplateExpression(node)) {
        reject("unsupported_control_flow", node);
      }
      if (ts.isIdentifier(node)) {
        const parent = node.parent;
        const isDeclarationName = (ts.isParameter(parent) || ts.isVariableDeclaration(parent) ||
          ts.isFunctionDeclaration(parent) || ts.isFunctionExpression(parent)) && parent.name === node;
        const isPropertyName = (ts.isPropertyAccessExpression(parent) && parent.name === node) ||
          (ts.isPropertyAssignment(parent) && parent.name === node);
        if (!isDeclarationName && !isPropertyName) {
          const symbol = checker.getSymbolAtLocation(node);
          if (!symbol) reject("dynamic_dependency", node);
          const resolved = resolveAlias(symbol, node);
          if (!intrinsicMath(resolved)) {
            const declarations = resolved.declarations || [];
            if (declarations.length === 0 || declarations.every((item) => item.getSourceFile?.().isDeclarationFile)) {
              reject("dynamic_dependency", node);
            }
          }
        }
      }
      ts.forEachChild(node, (child) => visit(child, false));
    }
    let completed = false;
    try {
      visit(functionNode, true);
      completed = true;
    } finally {
      state.active.delete(functionNode);
      if (completed) state.done.add(functionNode);
    }
  }

  function proveTopLevel(modules, state) {
    for (const [logicalPath, sourceFile] of modules) {
      for (const statement of sourceFile.statements) {
        if (ts.isImportDeclaration(statement)) {
          if (!statement.importClause) reject("top_level_side_effect", statement);
          continue;
        }
        if (ts.isExportDeclaration(statement)) continue;
        if (ts.isExportAssignment(statement) && !statement.isExportEquals && ts.isIdentifier(statement.expression)) {
          continue;
        }
        if (ts.isFunctionDeclaration(statement)) continue;
        if (ts.isVariableStatement(statement)) {
          if ((statement.declarationList.flags & ts.NodeFlags.Const) === 0) {
            reject("top_level_side_effect", statement);
          }
          for (const declaration of statement.declarationList.declarations) {
            if (!ts.isIdentifier(declaration.name) || !declaration.initializer) {
              reject("top_level_initializer_unproven", declaration);
            }
            const symbol = symbolAt(declaration.name);
            if (ts.isFunctionExpression(declaration.initializer) || ts.isArrowFunction(declaration.initializer)) {
              continue;
            }
            let domain;
            try {
              domain = evaluateModuleConst(symbol, state, declaration);
            } catch (error) {
              if (error instanceof Rejection && [
                "closure_unproven",
                "dynamic_dependency",
                "unsupported_control_flow",
                "mutable_capture",
              ].includes(error.code)) {
                reject("top_level_side_effect", declaration);
              }
              throw error;
            }
            if (singleton(domain) === undefined) reject("top_level_initializer_unproven", declaration);
          }
          continue;
        }
        if (ts.isEmptyStatement(statement)) continue;
        reject("top_level_side_effect", statement || logicalPath);
      }
    }
  }

  function validateTopLevelInitializer(initializer, declaration, state) {
    function visit(node) {
      if (ts.isCallExpression(node)) {
        if (node !== initializer || !ts.isIdentifier(node.expression)) {
          reject("top_level_initializer_unproven", node);
        }
        const helperSymbol = resolveAlias(symbolAt(node.expression), node.expression);
        const helperDeclaration = declarationForSymbol(helperSymbol, node.expression);
        if (ts.isVariableDeclaration(helperDeclaration) &&
            helperDeclaration.getSourceFile() === declaration.getSourceFile() &&
            helperDeclaration.getStart() >= declaration.getStart()) {
          reject("top_level_initializer_unproven", node.expression);
        }
        for (const argument of node.arguments) {
          if (literalValue(argument) !== undefined) continue;
          if (!ts.isIdentifier(argument)) reject("top_level_initializer_unproven", argument);
          const argumentSymbol = resolveAlias(symbolAt(argument), argument);
          const argumentDeclaration = variableDeclarationForSymbol(argumentSymbol, argument);
          if (!isConstDeclaration(argumentDeclaration)) reject("top_level_initializer_unproven", argument);
          if (argumentDeclaration.getSourceFile() === declaration.getSourceFile() &&
              argumentDeclaration.getStart() >= declaration.getStart()) {
            reject("top_level_initializer_unproven", argument);
          }
          const argumentDomain = evaluateModuleConst(argumentSymbol, state, argument);
          if (singleton(argumentDomain) === undefined) reject("top_level_initializer_unproven", argument);
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(initializer);
  }

  function evaluateModuleConst(symbol, state, node = null) {
    const resolved = resolveAlias(symbol, node);
    if (state.constDomains.has(resolved)) return state.constDomains.get(resolved);
    if (state.constActive.has(resolved)) reject("top_level_initializer_unproven", node);
    const declaration = variableDeclarationForSymbol(resolved, node);
    if (!isConstDeclaration(declaration) || !declaration.initializer) {
      reject("mutable_capture", declaration);
    }
    if (ts.isFunctionExpression(declaration.initializer) || ts.isArrowFunction(declaration.initializer)) {
      reject("top_level_initializer_unproven", declaration);
    }
    const current = state.constDeclarationStack.at(-1);
    if (current && current.getSourceFile() === declaration.getSourceFile() &&
        declaration.getStart() >= current.getStart()) {
      reject("top_level_initializer_unproven", declaration);
    }
    state.constActive.add(resolved);
    state.constDeclarationStack.push(declaration);
    let domain;
    try {
      validateTopLevelInitializer(declaration.initializer, declaration, state);
      domain = evaluateExpression(declaration.initializer, new Map(), state);
    } finally {
      state.constDeclarationStack.pop();
      state.constActive.delete(resolved);
    }
    if (singleton(domain) === undefined) reject("top_level_initializer_unproven", declaration);
    state.constDomains.set(resolved, domain);
    state.dependencyBindings.add(bindingId(resolved, declaration));
    return domain;
  }

  function evaluateIdentifier(identifier, environment, state) {
    const symbol = resolveAlias(symbolAt(identifier), identifier);
    if (environment.has(symbol)) return environment.get(symbol);
    const declaration = declarationForSymbol(symbol, identifier);
    if (ts.isVariableDeclaration(declaration)) {
      if (containingFunction(declaration)) reject("unsupported_control_flow", identifier);
      if (isLetDeclaration(declaration)) reject("mutable_capture", identifier);
      return evaluateModuleConst(symbol, state, identifier);
    }
    reject("closure_unproven", identifier);
  }

  function evaluateCall(call, environment, state) {
    const argumentsDomains = call.arguments.map((argument) => evaluateExpression(argument, environment, state));
    if (ts.isPropertyAccessExpression(call.expression)) {
      const receiver = call.expression.expression;
      if (!ts.isIdentifier(receiver) || !intrinsicMath(symbolAt(receiver))) reject("dynamic_dependency", call);
      const name = call.expression.name.text;
      if (name === "abs" && argumentsDomains.length === 1) return mathAbs(argumentsDomains[0], call);
      if ((name === "min" || name === "max") && argumentsDomains.length >= 1) {
        return mathMinMax(argumentsDomains, name, call);
      }
      reject("dynamic_dependency", call);
    }
    if (!ts.isIdentifier(call.expression)) reject("dynamic_dependency", call);
    const symbol = resolveAlias(symbolAt(call.expression), call.expression);
    return evaluateFunction(symbol, argumentsDomains, state, call, environment);
  }

  function evaluateExpression(expression, environment, state) {
    const literal = literalDomain(expression);
    if (literal) return literal;
    if (ts.isParenthesizedExpression(expression)) return evaluateExpression(expression.expression, environment, state);
    if (ts.isIdentifier(expression)) return evaluateIdentifier(expression, environment, state);
    if (ts.isPrefixUnaryExpression(expression)) {
      const operand = evaluateExpression(expression.operand, environment, state);
      if (expression.operator === ts.SyntaxKind.PlusToken) {
        if (operand.kind !== "integer") reject("interval_unproven", expression);
        return operand;
      }
      if (expression.operator === ts.SyntaxKind.MinusToken) return negate(operand, expression);
      if (expression.operator === ts.SyntaxKind.ExclamationToken) return complementBoolean(operand, expression);
      reject("unsupported_control_flow", expression);
    }
    if (ts.isBinaryExpression(expression)) {
      const operator = operatorText(expression.operatorToken.kind);
      if (!operator) reject("unsupported_control_flow", expression);
      if (operator === "&&" || operator === "||") {
        const left = evaluateExpression(expression.left, environment, state);
        if (left.kind !== "boolean") reject("interval_unproven", expression.left);
        const values = [];
        if (operator === "&&" && left.values.includes(false)) values.push(false);
        if (operator === "||" && left.values.includes(true)) values.push(true);
        if ((operator === "&&" && left.values.includes(true)) ||
            (operator === "||" && left.values.includes(false))) {
          const desired = operator === "&&";
          for (const refined of refineCondition(expression.left, environment, desired, state)) {
            const right = evaluateExpression(expression.right, refined, state);
            if (right.kind !== "boolean") reject("interval_unproven", expression.right);
            values.push(...right.values);
          }
        }
        return boolSet(values);
      }
      const left = evaluateExpression(expression.left, environment, state);
      const right = evaluateExpression(expression.right, environment, state);
      if (operator === "+") return add(left, right, expression);
      if (operator === "-") return subtract(left, right, expression);
      if (operator === "*") return multiply(left, right, expression);
      if (operator === "%") return remainder(left, right, expression);
      return compareDomains(left, right, operator, expression);
    }
    if (ts.isConditionalExpression(expression)) {
      const condition = evaluateExpression(expression.condition, environment, state);
      if (condition.kind !== "boolean") reject("interval_unproven", expression.condition);
      const alternatives = [];
      if (condition.values.includes(true)) {
        alternatives.push(...refineCondition(expression.condition, environment, true, state)
          .map((env) => evaluateExpression(expression.whenTrue, env, state)));
      }
      if (condition.values.includes(false)) {
        alternatives.push(...refineCondition(expression.condition, environment, false, state)
          .map((env) => evaluateExpression(expression.whenFalse, env, state)));
      }
      return unionDomains(alternatives, expression);
    }
    if (ts.isCallExpression(expression)) return evaluateCall(expression, environment, state);
    reject("unsupported_control_flow", expression);
  }

  function literalValue(node) {
    const domain = literalDomain(node);
    if (domain) return singleton(domain);
    if (ts.isPrefixUnaryExpression(node) && ts.isNumericLiteral(node.operand) &&
        [ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken].includes(node.operator)) {
      const unsigned = parseIntegerLiteral(node.operand);
      return assertSafeInteger(node.operator === ts.SyntaxKind.MinusToken ? -unsigned : unsigned, node);
    }
    return undefined;
  }

  function domainContains(domain, value) {
    if (domain.kind === "integer") return domain.intervals.some(([a, b]) => a <= value && value <= b);
    return domain.values.includes(value);
  }

  function excludeValue(domain, value, node) {
    if (domain.kind === "integer") {
      return intSet(domain.intervals.flatMap(([a, b]) => {
        if (value < a || value > b) return [[a, b]];
        return [a <= value - 1 ? [a, value - 1] : null, value + 1 <= b ? [value + 1, b] : null]
          .filter(Boolean);
      }), node);
    }
    if (domain.kind === "boolean") return boolSet(domain.values.filter((item) => item !== value));
    if (domain.kind === "enum") return enumSet(domain.values.filter((item) => item !== value), node);
    return bottom();
  }

  function intersectComparison(domain, operator, value, desired, node) {
    if ((operator === "===" || operator === "!==")) {
      const equalityDesired = operator === "===" ? desired : !desired;
      if (equalityDesired) {
        if (!domainContains(domain, value)) return bottom();
        if (typeof value === "number") return intSet([[value, value]], node);
        if (typeof value === "boolean") return boolSet([value]);
        return enumSet([value], node);
      }
      return excludeValue(domain, value, node);
    }
    if (domain.kind !== "integer" || typeof value !== "number") return domain;
    let minimum = MIN_SAFE;
    let maximum = MAX_SAFE;
    const effective = desired ? operator : ({ "<": ">=", "<=": ">", ">": "<=", ">=": "<" })[operator];
    if (effective === "<") maximum = value - 1;
    else if (effective === "<=") maximum = value;
    else if (effective === ">") minimum = value + 1;
    else if (effective === ">=") minimum = value;
    else return domain;
    if (!Number.isSafeInteger(minimum) || !Number.isSafeInteger(maximum)) return bottom();
    return intSet(domain.intervals.flatMap(([a, b]) => {
      const low = Math.max(a, minimum);
      const high = Math.min(b, maximum);
      return low <= high ? [[low, high]] : [];
    }), node);
  }

  function refineAtomic(binary, environment, desired) {
    const operator = operatorText(binary.operatorToken.kind);
    if (!["<", "<=", ">", ">=", "===", "!=="].includes(operator)) return [environment];
    let identifier = null;
    let literal = undefined;
    let effective = operator;
    if (ts.isIdentifier(binary.left)) {
      identifier = binary.left;
      literal = literalValue(binary.right);
    } else if (ts.isIdentifier(binary.right)) {
      identifier = binary.right;
      literal = literalValue(binary.left);
      effective = ({ "<": ">", "<=": ">=", ">": "<", ">=": "<=", "===": "===", "!==": "!==" })[operator];
    }
    if (!identifier || literal === undefined) return [environment];
    const symbol = resolveAlias(symbolAt(identifier), identifier);
    if (!environment.has(symbol)) return [environment];
    const narrowed = intersectComparison(environment.get(symbol), effective, literal, desired, binary);
    if (narrowed.kind === "bottom") return [];
    const copy = new Map(environment);
    copy.set(symbol, narrowed);
    return [copy];
  }

  function refineCondition(condition, environment, desired, state) {
    if (ts.isParenthesizedExpression(condition)) return refineCondition(condition.expression, environment, desired, state);
    if (ts.isPrefixUnaryExpression(condition) && condition.operator === ts.SyntaxKind.ExclamationToken) {
      return refineCondition(condition.operand, environment, !desired, state);
    }
    if (ts.isBinaryExpression(condition)) {
      const operator = operatorText(condition.operatorToken.kind);
      if (operator === "&&") {
        if (desired) {
          return refineCondition(condition.left, environment, true, state)
            .flatMap((env) => refineCondition(condition.right, env, true, state));
        }
        return [
          ...refineCondition(condition.left, environment, false, state),
          ...refineCondition(condition.left, environment, true, state)
            .flatMap((env) => refineCondition(condition.right, env, false, state)),
        ];
      }
      if (operator === "||") {
        if (!desired) {
          return refineCondition(condition.left, environment, false, state)
            .flatMap((env) => refineCondition(condition.right, env, false, state));
        }
        return [
          ...refineCondition(condition.left, environment, true, state),
          ...refineCondition(condition.left, environment, false, state)
            .flatMap((env) => refineCondition(condition.right, env, true, state)),
        ];
      }
      return refineAtomic(condition, environment, desired);
    }
    return [environment];
  }

  function analyzeSwitch(statement, environment, state) {
    const discriminator = evaluateExpression(statement.expression, environment, state);
    if (!["integer", "boolean", "enum"].includes(discriminator.kind)) {
      reject("interval_unproven", statement.expression);
    }
    const clauses = statement.caseBlock.clauses;
    const cases = clauses.filter(ts.isCaseClause);
    const defaults = clauses.filter(ts.isDefaultClause);
    if (cases.length > MAX_SWITCH_CASES || defaults.length !== 1) reject("unsupported_control_flow", statement);
    const seen = new Set();
    const returns = [];
    for (const clause of clauses) {
      if (clause.statements.length === 0 || !ts.isReturnStatement(clause.statements.at(-1))) {
        reject("unsupported_control_flow", clause);
      }
      if (ts.isCaseClause(clause)) {
        const value = literalValue(clause.expression);
        if (value === undefined) reject("unsupported_control_flow", clause.expression);
        const key = `${typeof value}:${String(value)}`;
        if (seen.has(key)) reject("unsupported_control_flow", clause.expression);
        seen.add(key);
      }
      const outcome = analyzeStatementList(clause.statements, [new Map(environment)], state);
      if (outcome.fallsThrough.length !== 0 || outcome.returns.length === 0) {
        reject("unsupported_control_flow", clause);
      }
      returns.push(...outcome.returns);
    }
    return { returns, fallsThrough: [] };
  }

  function analyzeStatement(statement, environment, state) {
    if (ts.isBlock(statement)) return analyzeStatementList(statement.statements, [environment], state);
    if (ts.isFunctionDeclaration(statement)) return { returns: [], fallsThrough: [environment] };
    if (ts.isEmptyStatement(statement)) return { returns: [], fallsThrough: [environment] };
    if (ts.isVariableStatement(statement)) {
      let environments = [environment];
      for (const declaration of statement.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || !declaration.initializer) reject("unsupported_control_flow", declaration);
        const symbol = resolveAlias(symbolAt(declaration.name), declaration.name);
        environments = environments.map((env) => {
          const value = evaluateExpression(declaration.initializer, env, state);
          const copy = new Map(env);
          copy.set(symbol, value);
          state.dependencyBindings.add(bindingId(symbol, declaration));
          return copy;
        });
      }
      return { returns: [], fallsThrough: environments };
    }
    if (ts.isReturnStatement(statement)) {
      if (!statement.expression) reject("interval_unproven", statement);
      return { returns: [evaluateExpression(statement.expression, environment, state)], fallsThrough: [] };
    }
    if (ts.isIfStatement(statement)) {
      const condition = evaluateExpression(statement.expression, environment, state);
      if (condition.kind !== "boolean") reject("interval_unproven", statement.expression);
      const returns = [];
      const fallsThrough = [];
      if (condition.values.includes(true)) {
        for (const env of refineCondition(statement.expression, environment, true, state)) {
          const result = analyzeStatement(statement.thenStatement, env, state);
          returns.push(...result.returns);
          fallsThrough.push(...result.fallsThrough);
        }
      }
      if (condition.values.includes(false)) {
        const falseEnvs = refineCondition(statement.expression, environment, false, state);
        if (statement.elseStatement) {
          for (const env of falseEnvs) {
            const result = analyzeStatement(statement.elseStatement, env, state);
            returns.push(...result.returns);
            fallsThrough.push(...result.fallsThrough);
          }
        } else {
          fallsThrough.push(...falseEnvs);
        }
      }
      return { returns, fallsThrough };
    }
    if (ts.isSwitchStatement(statement)) return analyzeSwitch(statement, environment, state);
    reject("unsupported_control_flow", statement);
  }

  function analyzeStatementList(statements, initialEnvironments, state) {
    let environments = initialEnvironments;
    const returns = [];
    for (const statement of statements) {
      if (environments.length === 0) break;
      const next = [];
      for (const environment of environments) {
        const result = analyzeStatement(statement, environment, state);
        returns.push(...result.returns);
        next.push(...result.fallsThrough);
      }
      environments = next;
      if (environments.length > 64) reject("interval_unproven", statement);
    }
    return { returns, fallsThrough: environments };
  }

  function evaluateFunction(symbol, argumentDomains, state, callNode = null, captureEnvironment = null) {
    const resolved = resolveAlias(symbol, callNode);
    const id = bindingId(resolved, callNode);
    if (state.activeFunctions.has(resolved)) reject("closure_unproven", callNode);
    if (state.activeFunctions.size >= 32) reject("closure_unproven", callNode);
    const functionNode = functionNodeForSymbol(resolved, callNode);
    scanFunctionSyntax(functionNode);
    ensureFunctionSignature(functionNode);
    if (argumentDomains.length !== functionNode.parameters.length) reject("interval_unproven", callNode || functionNode);
    const environment = new Map(captureEnvironment || []);
    for (let index = 0; index < functionNode.parameters.length; index += 1) {
      const parameter = functionNode.parameters[index];
      const parameterSymbol = resolveAlias(symbolAt(parameter.name), parameter.name);
      environment.set(parameterSymbol, argumentDomains[index]);
      state.dependencyBindings.add(bindingId(parameterSymbol, parameter));
    }
    state.activeFunctions.add(resolved);
    state.dependencyBindings.add(id);
    let result;
    try {
      if (ts.isBlock(functionNode.body)) {
        result = analyzeStatementList(functionNode.body.statements, [environment], state);
      } else {
        result = { returns: [evaluateExpression(functionNode.body, environment, state)], fallsThrough: [] };
      }
    } finally {
      state.activeFunctions.delete(resolved);
    }
    if (result.fallsThrough.length !== 0 || result.returns.length === 0) {
      reject("interval_unproven", functionNode);
    }
    return unionDomains(result.returns, functionNode);
  }

  function topLevelEvidence(modules) {
    return modules.map(([logicalPath, sourceFile]) => ({
      logical_path: logicalPath,
      statement_count: sourceFile.statements.length,
      status: "proved",
    }));
  }

  function proveTarget({ moduleRelpath, exportName, parameterDomains = [] }) {
    if (typeof moduleRelpath !== "string" || typeof exportName !== "string") {
      reject("closure_unproven", moduleRelpath || null);
    }
    const target = resolveTarget(moduleRelpath, exportName);
    const moduleClosure = moduleDependencyClosure(target.sourceFile);
    const domainByBindingId = new Map();
    for (const item of parameterDomains) {
      if (!item || typeof item.parameter_binding_id !== "string" || domainByBindingId.has(item.parameter_binding_id)) {
        reject("interval_unproven", target.functionNode);
      }
      domainByBindingId.set(item.parameter_binding_id, parseParameterDomain(item.domain, target.functionNode));
    }
    ensureFunctionSignature(target.functionNode);
    const argumentDomains = target.functionNode.parameters.map((parameter) => {
      const id = bindingId(symbolAt(parameter.name), parameter);
      const domain = domainByBindingId.get(id);
      if (!domain) reject("interval_unproven", parameter);
      return domain;
    });
    if (domainByBindingId.size !== argumentDomains.length) reject("interval_unproven", target.functionNode);

    const state = {
      activeFunctions: new Set(),
      constActive: new Set(),
      constDeclarationStack: [],
      constDomains: new Map(),
      dependencyBindings: new Set(),
    };
    const returnDomain = evaluateFunction(target.leafSymbol, argumentDomains, state, target.functionNode);
    if (returnDomain.kind !== "integer") reject("interval_unproven", target.functionNode);
    // Give selected mutable captures the specific failure before the complete
    // module-evaluation proof rejects unrelated top-level effects.
    proveTopLevel(moduleClosure.modules, state);
    const moduleEvidence = moduleClosure.modules.map(([logicalPath, sourceFile]) => ({
      logical_path: logicalPath,
      source_sha256: snapshotSha256(sourceFile),
    }));
    const dependencyBindingIds = [...state.dependencyBindings].sort();
    const closureEvidence = {
      schema: "source_graph_closure.v1",
      modules: moduleEvidence,
      binding_ids: dependencyBindingIds,
      module_count: moduleEvidence.length,
      source_bytes: moduleClosure.byteCount,
      top_level: topLevelEvidence(moduleClosure.modules),
    };
    const proof = {
      schema: "source_graph_proof.v1",
      status: "proved",
      target: {
        module_relpath: moduleRelpath,
        export_name: exportName,
        binding_id: bindingId(target.leafSymbol, target.functionNode),
      },
      parameter_domains: target.functionNode.parameters.map((parameter, index) => ({
        parameter_binding_id: bindingId(symbolAt(parameter.name), parameter),
        domain: serializeDomain(argumentDomains[index]),
      })),
      return_domain: serializeDomain(returnDomain),
      dependency_closure: closureEvidence,
      closure_evidence_sha256: canonicalSha256(closureEvidence),
      dynamic_dependencies: [],
    };
    return proof;
  }

  return Object.freeze({
    proveTarget,
    domains: Object.freeze({ bottom, boolSet, enumSet, intSet, serializeDomain, unionDomains }),
  });
}

function safeRejection(error) {
  const allowed = new Set([
    "source_changed",
    "source_utf8_invalid",
    "source_span_invalid",
    "source_path_normalization_conflict",
    "import_path_spelling_mismatch",
    "closure_unproven",
    "closure_symlink_forbidden",
    "mutable_capture",
    "top_level_side_effect",
    "top_level_initializer_unproven",
    "dynamic_dependency",
    "unsupported_control_flow",
    "invalid_export_identifier",
    "interval_unproven",
    "bundle_security_rejected",
  ]);
  const code = error instanceof Rejection && allowed.has(error.code) ? error.code : "unclassified_internal_result";
  const logicalPath = error instanceof Rejection ? error.logicalPath : null;
  return { schema: SOURCE_GRAPH_VERSION, status: "rejected", error_code: code, logical_path: logicalPath };
}

function rejectionSummary(codes) {
  const counts = new Map();
  for (const code of codes) counts.set(code, (counts.get(code) || 0) + 1);
  return [...counts.entries()]
    .sort(([left], [right]) => compareUtf8(left, right))
    .map(([code, count]) => ({ code, count }));
}

function proofGraphContext(snapshot, graph) {
  return {
    sourceFileByLogicalPath(logicalPath) {
      return snapshot.records.get(logicalPath)?.sourceFile;
    },
    logicalPathOfSourceFile(sourceFile) {
      return logicalFromVirtual(sourceFile.fileName);
    },
    resolveModule(fromLogicalPath, specifier) {
      const logicalPath = resolveSpecifier(snapshot, fromLogicalPath, specifier);
      return {
        logicalPath,
        sourceFile: snapshot.records.get(logicalPath)?.sourceFile,
        viaSymlink: pathUsesSymlink(logicalPath, snapshot.symlinks),
      };
    },
    bindingIdForSymbol(symbol) {
      return graph.descriptorBySymbol.get(graph.resolvedSymbol(symbol))?.binding_id || null;
    },
    sha256ForSourceFile(sourceFile) {
      const logicalPath = logicalFromVirtual(sourceFile.fileName);
      return logicalPath ? snapshot.records.get(logicalPath)?.sha256 : null;
    },
    isIntrinsicMathSymbol(symbol) {
      return graph.resolvedSymbol(symbol) === graph.resolvedSymbol(graph.mathSymbol);
    },
  };
}

function createProof(request, snapshot, graph) {
  if (!request.target || typeof request.target !== "object" ||
      typeof request.target.module_relpath !== "string" ||
      typeof request.target.export_name !== "string" ||
      !Array.isArray(request.parameter_domains)) {
    throw new Rejection("closure_unproven", request.target?.module_relpath || null);
  }
  const engine = installProof({
    ts,
    checker: graph.checker,
    graphContext: proofGraphContext(snapshot, graph),
    Rejection,
    canonicalSha256,
  });
  const internal = engine.proveTarget({
    moduleRelpath: normalizedLogicalPath(request.target.module_relpath),
    exportName: request.target.export_name,
    parameterDomains: request.parameter_domains,
  });
  const closure = {
    module_paths: internal.dependency_closure.modules.map((item) => item.logical_path),
    binding_ids: [...internal.dependency_closure.binding_ids],
  };
  return {
    target_binding_id: internal.target.binding_id,
    parameter_domains: internal.parameter_domains,
    result_domain: internal.return_domain,
    closure,
    closure_sha256: canonicalSha256(closure),
    dependency_evidence_sha256: internal.closure_evidence_sha256,
    module_evidence_sha256: canonicalSha256(internal.dependency_closure.modules),
    top_level_evidence_sha256: canonicalSha256(internal.dependency_closure.top_level),
  };
}

function captureEntrySource(target) {
  const moduleRelpath = normalizedLogicalPath(target.module_relpath);
  const exportName = target.export_name;
  if (typeof exportName !== "string" ||
      (exportName !== "default" &&
       !ts.isIdentifierText(exportName, ts.ScriptTarget.ES2022, ts.LanguageVariant.Standard))) {
    throw new Rejection("invalid_export_identifier", moduleRelpath);
  }
  const factory = ts.factory;
  const sourceFile = ts.createSourceFile(
    CAPTURE_ENTRY,
    "",
    ts.ScriptTarget.ES2022,
    false,
    ts.ScriptKind.JS,
  );
  const statement = factory.createExportDeclaration(
    undefined,
    false,
    factory.createNamedExports([
      factory.createExportSpecifier(
        false,
        factory.createIdentifier(exportName),
        factory.createIdentifier("__selected"),
      ),
    ]),
    factory.createStringLiteral(`./${moduleRelpath}`),
  );
  return ts.createPrinter({ newLine: ts.NewLineKind.LineFeed }).printFile(
    factory.updateSourceFile(sourceFile, [statement]),
  );
}

function verifySelectedBundle(bytes) {
  const source = strictUtf8(bytes, SELECTED_LOGICAL_PATH);
  const sourceFile = ts.createSourceFile(
    SELECTED_LOGICAL_PATH,
    source,
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.JS,
  );
  if (sourceFile.parseDiagnostics.length > 0) throw new Rejection("bundle_security_rejected");
  const sensitivityLiterals = new Set();
  function collectSensitivityLiterals(node) {
    if (ts.isStringLiteralLike(node)) {
      const value = node.text;
      const encoded = Buffer.from(value, "utf8");
      if (strictUtf8(encoded, SELECTED_LOGICAL_PATH) !== value) {
        throw new Rejection("bundle_security_rejected");
      }
      sensitivityLiterals.add(value);
    } else if (ts.isNumericLiteral(node)) {
      const value = Number(node.text);
      if (!Number.isSafeInteger(value)) {
        throw new Rejection("bundle_security_rejected");
      }
      sensitivityLiterals.add(String(value));
    }
    ts.forEachChild(node, collectSensitivityLiterals);
  }
  collectSensitivityLiterals(sourceFile);
  let exportCount = 0;
  for (const statement of sourceFile.statements) {
    if (ts.isImportDeclaration(statement) || ts.isExportAssignment(statement) ||
        hasModifier(statement, ts.SyntaxKind.ExportKeyword) ||
        hasModifier(statement, ts.SyntaxKind.DefaultKeyword)) {
      throw new Rejection("bundle_security_rejected");
    }
    if (!ts.isExportDeclaration(statement)) continue;
    if (statement.moduleSpecifier || !statement.exportClause ||
        !ts.isNamedExports(statement.exportClause) || statement.exportClause.elements.length !== 1) {
      throw new Rejection("bundle_security_rejected");
    }
    const element = statement.exportClause.elements[0];
    if (!ts.isIdentifier(element.name) || element.name.text !== "__selected") {
      throw new Rejection("bundle_security_rejected");
    }
    exportCount += 1;
  }
  if (exportCount !== 1) throw new Rejection("bundle_security_rejected");
  const orderedLiterals = [...sensitivityLiterals].sort(compareUtf8);
  if (orderedLiterals.reduce((total, value) => total + Buffer.byteLength(value, "utf8"), 0) > bytes.length) {
    throw new Rejection("bundle_security_rejected");
  }
  return orderedLiterals;
}

async function createCapture(request, snapshot, graph, proof) {
  if (esbuild.version !== FIXED_ESBUILD_VERSION) throw new Rejection("bundle_security_rejected");
  const entrySource = captureEntrySource(request.target);
  const targetModulePath = normalizedLogicalPath(request.target.module_relpath);
  const targetSpecifier = `./${targetModulePath}`;
  const expectedModulePaths = new Set(proof.closure.module_paths);
  const symbolClosurePaths = new Set();
  const bindingIds = new Set(proof.closure.binding_ids);
  for (const module of graph.modules) {
    if (module.bindings.some((binding) => bindingIds.has(binding.binding_id))) {
      symbolClosurePaths.add(module.logical_path);
    }
  }
  if (symbolClosurePaths.size === 0) throw new Rejection("bundle_security_rejected");

  const requestedRoot = typeof request.temporary_root === "string"
    ? request.temporary_root
    : "";
  if (!path.isAbsolute(requestedRoot)) throw new Rejection("bundle_security_rejected");
  let requestedStat;
  let requestedReal;
  try {
    requestedStat = await fs.lstat(requestedRoot);
    requestedReal = await fs.realpath(requestedRoot);
  } catch {
    throw new Rejection("bundle_security_rejected");
  }
  if (!requestedStat.isDirectory() || requestedStat.isSymbolicLink()
      || requestedReal !== requestedRoot
      || (typeof process.getuid === "function" && requestedStat.uid !== process.getuid())
      || (process.platform !== "win32" && (requestedStat.mode & 0o077) !== 0)) {
    throw new Rejection("bundle_security_rejected");
  }
  let marker;
  try {
    marker = await fs.readFile(path.join(requestedRoot, ".reweave-capture-job-v1"), "utf8");
  } catch {
    throw new Rejection("bundle_security_rejected");
  }
  if (marker !== "reweave-capture-private-job.v1\n") {
    throw new Rejection("bundle_security_rejected");
  }
  const temporaryRoot = await fs.mkdtemp(path.join(requestedRoot, "bundle-"));
  await fs.chmod(temporaryRoot, 0o700);
  try {
    let buildResult;
    try {
      buildResult = await esbuild.build({
        ...CAPTURE_BUNDLE_OPTIONS,
        absWorkingDir: temporaryRoot,
        entryPoints: [CAPTURE_ENTRY],
        outfile: "selected.js",
        plugins: [{
          name: "reweave-snapshot-only",
          setup(build) {
            build.onResolve({ filter: /.*/ }, (args) => {
              if (args.kind === "entry-point") {
                if (args.path !== CAPTURE_ENTRY) throw new Rejection("bundle_security_rejected");
                return { path: CAPTURE_ENTRY, namespace: "reweave-entry" };
              }
              const importer = args.pluginData?.logicalPath;
              if (typeof importer !== "string") throw new Rejection("bundle_security_rejected");
              const logicalPath = importer === CAPTURE_ENTRY
                ? (args.path === targetSpecifier ? targetModulePath : null)
                : snapshot.records.get(importer)?.resolution.get(args.path);
              if (typeof logicalPath !== "string") throw new Rejection("bundle_security_rejected", importer);
              if (!expectedModulePaths.has(logicalPath)) throw new Rejection("bundle_security_rejected", logicalPath);
              return {
                path: logicalPath,
                namespace: "reweave-snapshot",
                pluginData: { logicalPath },
              };
            });
            build.onLoad({ filter: /.*/, namespace: "reweave-entry" }, (args) => {
              if (args.path !== CAPTURE_ENTRY) throw new Rejection("bundle_security_rejected");
              return {
                contents: entrySource,
                loader: "js",
                resolveDir: "/",
                pluginData: { logicalPath: CAPTURE_ENTRY },
              };
            });
            build.onLoad({ filter: /.*/, namespace: "reweave-snapshot" }, (args) => {
              const record = snapshot.records.get(args.path);
              if (!record || record.sha256 !== sha256Bytes(record.bytes)) {
                throw new Rejection("source_changed", args.path);
              }
              return {
                contents: record.bytes,
                loader: "js",
                resolveDir: "/",
                pluginData: { logicalPath: record.logicalPath },
              };
            });
          },
        }],
      });
    } catch {
      throw new Rejection("bundle_security_rejected");
    }

    if (buildResult.warnings.length !== 0 || buildResult.outputFiles?.length !== 1 || !buildResult.metafile) {
      throw new Rejection("bundle_security_rejected");
    }
    const outputFile = buildResult.outputFiles[0];
    if (path.basename(outputFile.path) !== "selected.js") throw new Rejection("bundle_security_rejected");
    const selectedBytes = Buffer.from(outputFile.contents);
    if (selectedBytes.length === 0 || selectedBytes.length > MAX_SELECTED_BYTES) {
      throw new Rejection("bundle_security_rejected");
    }
    const outputEntries = Object.entries(buildResult.metafile.outputs);
    if (outputEntries.length !== 1) throw new Rejection("bundle_security_rejected");
    const output = outputEntries[0][1];
    if (output.imports.length !== 0 || canonicalJson(output.exports) !== canonicalJson(["__selected"])) {
      throw new Rejection("bundle_security_rejected");
    }

    const metafileInputs = [];
    let entrySeen = false;
    for (const inputName of Object.keys(buildResult.metafile.inputs)) {
      if (inputName === `reweave-entry:${CAPTURE_ENTRY}`) {
        entrySeen = true;
        continue;
      }
      const prefix = "reweave-snapshot:";
      if (!inputName.startsWith(prefix)) throw new Rejection("bundle_security_rejected");
      const logicalPath = inputName.slice(prefix.length);
      if (!expectedModulePaths.has(logicalPath)) throw new Rejection("bundle_security_rejected", logicalPath);
      metafileInputs.push(logicalPath);
    }
    metafileInputs.sort(compareUtf8);
    if (!entrySeen || symbolClosurePaths.size === 0 ||
        [...symbolClosurePaths].some((logicalPath) => !metafileInputs.includes(logicalPath))) {
      throw new Rejection("bundle_security_rejected");
    }
    const sensitivityLiterals = verifySelectedBundle(selectedBytes);

    return {
      schema: "selected_bundle.v1",
      bundle_contract_version: CAPTURE_BUNDLE_CONTRACT_VERSION,
      logical_path: SELECTED_LOGICAL_PATH,
      source_base64: selectedBytes.toString("base64"),
      selected_bundle_sha256: sha256Bytes(selectedBytes),
      size_bytes: selectedBytes.length,
      source_graph_version: SOURCE_GRAPH_VERSION,
      typescript_version: ts.version,
      esbuild_version: esbuild.version,
      bundle_options_sha256: canonicalSha256(CAPTURE_BUNDLE_OPTIONS),
      capture_entry_sha256: sha256Bytes(Buffer.from(entrySource, "utf8")),
      target_binding_id: proof.target_binding_id,
      closure_sha256: proof.closure_sha256,
      module_evaluation_paths: [...expectedModulePaths].sort(compareUtf8),
      symbol_closure_paths: [...symbolClosurePaths].sort(compareUtf8),
      metafile_inputs: metafileInputs,
      sensitivity_literals: sensitivityLiterals,
    };
  } finally {
    await fs.rm(temporaryRoot, { recursive: true, force: true });
  }
}

async function readRequest() {
  let data = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) data += chunk;
  try {
    return JSON.parse(data);
  } catch {
    throw new Rejection("source_changed");
  }
}

async function main() {
  try {
    const request = await readRequest();
    if (!request || request.schema !== REQUEST_SCHEMA || !["graph", "prove", "capture"].includes(request.mode) ||
        typeof request.project_id !== "string" || !request.project_id ||
        typeof request.scope_snapshot_sha256 !== "string" || !/^[0-9a-f]{64}$/u.test(request.scope_snapshot_sha256) ||
        typeof request.source_identity_sha256 !== "string" || !/^[0-9a-f]{64}$/u.test(request.source_identity_sha256) ||
        !Array.isArray(request.entry_modules) || request.entry_modules.length === 0 ||
        (request.isolate_entry_failures !== undefined && typeof request.isolate_entry_failures !== "boolean") ||
        (request.mode !== "graph" && request.isolate_entry_failures === true)) {
      throw new Rejection("source_changed");
    }
    const snapshot = createSnapshot(request);
    const isolateEntryFailures = request.mode === "graph" && request.isolate_entry_failures === true;
    const directEntryRejections = [];
    const usableEntryModules = [];
    const seenEntryModules = new Set();
    for (const entry of request.entry_modules) {
      const logical = normalizedLogicalPath(entry);
      if (isolateEntryFailures && seenEntryModules.has(logical)) continue;
      seenEntryModules.add(logical);
      if (!snapshot.records.has(logical)) throw new Rejection("source_changed", logical);
      if (pathUsesSymlink(logical, snapshot.symlinks)) {
        if (!isolateEntryFailures) throw new Rejection("closure_symlink_forbidden", logical);
        directEntryRejections.push("closure_symlink_forbidden");
        continue;
      }
      usableEntryModules.push(logical);
    }
    const programState = createProgram(snapshot, usableEntryModules, isolateEntryFailures);
    programState.entryRejections.push(...directEntryRejections);
    const graph = createGraph(snapshot, programState);
    const result = {
      schema: SOURCE_GRAPH_VERSION,
      status: "ok",
      project_id: request.project_id,
      scope_snapshot_sha256: request.scope_snapshot_sha256,
      source_identity_sha256: request.source_identity_sha256,
      modules: graph.modules,
    };
    if (isolateEntryFailures) {
      result.rejection_summary = rejectionSummary(programState.entryRejections);
    }
    if (["prove", "capture"].includes(request.mode)) {
      result.proof = createProof(request, snapshot, graph);
    }
    if (request.mode === "capture") {
      result.capture = await createCapture(request, snapshot, graph, result.proof);
    }
    return result;
  } catch (error) {
    return safeRejection(error);
  }
}

process.stdout.write(`${JSON.stringify(await main())}\n`);
