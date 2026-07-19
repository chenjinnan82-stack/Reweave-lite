import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { build, version as esbuildVersion } from "esbuild";
import * as ts from "typescript";

class Rejection extends Error {
  constructor(code, logicalPath = "") {
    super(code);
    this.code = code;
    this.logicalPath = logicalPath;
  }
}

const input = JSON.parse(await new Promise((resolve) => {
  let data = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => { data += chunk; });
  process.stdin.on("end", () => resolve(data));
}));

const forbiddenIdentifiers = new Set([
  "Cache", "Date", "EventSource", "Function", "Notification", "Promise",
  "SharedWorker", "WebAssembly", "WebSocket", "Worker", "XMLHttpRequest",
  "alert", "caches", "confirm", "console", "cookieStore", "crypto",
  "document", "eval", "fetch", "globalThis", "history", "indexedDB",
  "localStorage", "location", "navigator", "open", "performance", "print",
  "process", "queueMicrotask", "requestAnimationFrame", "require",
  "sendBeacon", "sessionStorage", "setInterval", "setTimeout", "window",
]);
const forbiddenProperties = new Set([
  "apply", "bind", "call", "closest", "constructor", "contentWindow",
  "cookie", "dispatchEvent", "getRootNode", "innerHTML", "insertAdjacentHTML",
  "outerHTML", "ownerDocument", "parentElement", "parentNode", "remove",
  "srcdoc", "style",
]);
const allowedGlobals = new Set([
  "Array", "Boolean", "JSON", "Math", "Number", "Object", "String",
  "parseFloat", "parseInt", "undefined",
]);
const allowedMathMethods = new Set([
  "abs", "ceil", "floor", "max", "min", "round", "sign", "trunc",
]);
const allowedNumberMethods = new Set(["isFinite", "isInteger", "isNaN"]);
const allowedJsonMethods = new Set(["parse", "stringify"]);
const allowedObjectMethods = new Set(["entries", "keys", "values"]);
const allowedArrayMethods = new Set([
  "concat", "every", "filter", "find", "findIndex", "flat", "includes",
  "indexOf", "join", "map", "reduce", "slice", "some",
]);
const allowedStringMethods = new Set([
  "endsWith", "includes", "indexOf", "slice", "startsWith", "substring",
  "toLowerCase", "toUpperCase", "trim",
]);
const allowedDomRead = new Set([
  "checked", "disabled", "hidden", "selectedIndex", "textContent", "value",
]);
const allowedDomWrite = new Set(allowedDomRead);
const allowedDomMethods = new Set([
  "addEventListener", "append", "cloneNode", "querySelector", "querySelectorAll",
  "removeAttribute", "removeEventListener", "replaceChildren", "setAttribute",
]);
const allowedEvents = new Set(["change", "click", "input", "reset", "select", "submit"]);
const computationAdapterEntry = "__reweave_adapter__/compute.js";
const computationCaptureEntry = "__reweave_capture__/selected.js";
const computationAdapterV2 = "computation_adapter.v2";
const deterministicAdapterOrigin = "deterministic_computation_adapter";

function parseModule(path, source) {
  const tree = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  if (tree.parseDiagnostics.length) throw new Rejection("javascript_syntax_invalid", path);
  return tree;
}

function staticString(node) {
  return node && ts.isStringLiteralLike(node) ? node.text : null;
}

function propertyName(node) {
  if (ts.isPropertyAccessExpression(node)) return node.name.text;
  if (ts.isElementAccessExpression(node)) {
    const value = staticString(node.argumentExpression);
    if (value === null) throw new Rejection("dynamic_property_access_forbidden");
    return value;
  }
  return null;
}

function rootIdentifier(node) {
  let current = node;
  while (ts.isPropertyAccessExpression(current) || ts.isElementAccessExpression(current)) current = current.expression;
  return ts.isIdentifier(current) ? current.text : null;
}

function isReferenceIdentifier(node) {
  const parent = node.parent;
  if (!parent) return true;
  if (
    ((ts.isFunctionDeclaration(parent) || ts.isFunctionExpression(parent) || ts.isArrowFunction(parent)
      || ts.isParameter(parent) || ts.isVariableDeclaration(parent) || ts.isImportSpecifier(parent)
      || ts.isImportClause(parent) || ts.isBindingElement(parent)) && parent.name === node)
    || (ts.isPropertyAccessExpression(parent) && parent.name === node)
    || (ts.isPropertyAssignment(parent) && parent.name === node && !parent.questionToken)
    || (ts.isMethodDeclaration(parent) && parent.name === node)
  ) return false;
  return true;
}

function collectNames(node, names) {
  function addBinding(name) {
    if (ts.isIdentifier(name)) names.add(name.text);
    else if (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) {
      for (const item of name.elements) if (ts.isBindingElement(item)) addBinding(item.name);
    }
  }
  function visit(current) {
    if (current !== node && ts.isFunctionLike(current)) return;
    if (ts.isVariableDeclaration(current) || ts.isParameter(current)) addBinding(current.name);
    if (ts.isFunctionDeclaration(current) && current.name) names.add(current.name.text);
    if (ts.isCatchClause(current) && current.variableDeclaration) addBinding(current.variableDeclaration.name);
    ts.forEachChild(current, visit);
  }
  visit(node);
}

function moduleNames(tree) {
  const names = new Set();
  for (const statement of tree.statements) {
    if (ts.isImportDeclaration(statement) && statement.importClause) {
      if (statement.importClause.name) names.add(statement.importClause.name.text);
      const bindings = statement.importClause.namedBindings;
      if (bindings && ts.isNamedImports(bindings)) for (const item of bindings.elements) names.add(item.name.text);
    }
    if (ts.isFunctionDeclaration(statement) && statement.name) names.add(statement.name.text);
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) collectNames(declaration, names);
    }
  }
  return names;
}

function moduleVariableNames(tree) {
  const names = new Set();
  for (const statement of tree.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) collectNames(declaration, names);
  }
  return names;
}

function moduleStaticScalarNames(tree) {
  const values = new Set();
  function staticScalar(node) {
    if (!node) return false;
    if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node)
        || node.kind === ts.SyntaxKind.TrueKeyword || node.kind === ts.SyntaxKind.FalseKeyword) {
      return true;
    }
    if (ts.isIdentifier(node)) return values.has(node.text);
    return ts.isPrefixUnaryExpression(node)
      && [ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken].includes(node.operator)
      && ts.isNumericLiteral(node.operand);
  }
  for (const statement of tree.statements) {
    // esbuild lowers proven source const declarations to `var` in the selected
    // bundle. Later writes are still rejected by the module-state checks.
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (ts.isIdentifier(declaration.name) && staticScalar(declaration.initializer)) {
        values.add(declaration.name.text);
      }
    }
  }
  return values;
}

function staticCaptureArgument(node, scalarNames) {
  if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node)
      || node.kind === ts.SyntaxKind.TrueKeyword || node.kind === ts.SyntaxKind.FalseKeyword) {
    return true;
  }
  if (ts.isIdentifier(node)) return scalarNames.has(node.text);
  return ts.isPrefixUnaryExpression(node)
    && [ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken].includes(node.operator)
    && ts.isNumericLiteral(node.operand);
}

function functionMap(trees) {
  const result = new Map();
  for (const [path, tree] of trees) {
    for (const statement of tree.statements) {
      if (ts.isFunctionDeclaration(statement) && statement.name) result.set(`${path}:${statement.name.text}`, statement);
      if (ts.isVariableStatement(statement)) {
        for (const declaration of statement.declarationList.declarations) {
          if (ts.isIdentifier(declaration.name) && declaration.initializer
              && (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer))) {
            result.set(`${path}:${declaration.name.text}`, declaration.initializer);
          }
        }
      }
    }
  }
  return result;
}

function resolveRelativeModule(fromPath, specifier) {
  if (!specifier.startsWith("./") && !specifier.startsWith("../")) return null;
  const parts = fromPath.split("/").slice(0, -1);
  for (const part of specifier.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (!parts.length) return null;
      parts.pop();
    } else {
      parts.push(part);
    }
  }
  const result = parts.join("/");
  return result.endsWith(".js") || result.endsWith(".mjs") ? result : null;
}

function exportedFunction(tree, exportedName) {
  const localFunctions = new Map();
  for (const statement of tree.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.name) {
      localFunctions.set(statement.name.text, statement);
      if (statement.name.text === exportedName
          && statement.modifiers?.some((item) => item.kind === ts.SyntaxKind.ExportKeyword)
          && !statement.modifiers?.some((item) => item.kind === ts.SyntaxKind.DefaultKeyword)) {
        return statement;
      }
    }
  }
  for (const statement of tree.statements) {
    if (!ts.isExportDeclaration(statement) || statement.moduleSpecifier
        || !statement.exportClause || !ts.isNamedExports(statement.exportClause)) continue;
    for (const item of statement.exportClause.elements) {
      if (item.name.text !== exportedName) continue;
      return localFunctions.get(item.propertyName?.text || item.name.text) || null;
    }
  }
  return null;
}

function hasOnlyNamedExport(tree, exportedName) {
  const names = [];
  for (const statement of tree.statements) {
    const modifiers = statement.modifiers || [];
    const isExported = modifiers.some((item) => item.kind === ts.SyntaxKind.ExportKeyword);
    const isDefault = modifiers.some((item) => item.kind === ts.SyntaxKind.DefaultKeyword);
    if (isExported) {
      if (isDefault) names.push("default");
      else if (ts.isFunctionDeclaration(statement) || ts.isClassDeclaration(statement)) {
        if (statement.name) names.push(statement.name.text);
      } else if (ts.isVariableStatement(statement)) {
        for (const declaration of statement.declarationList.declarations) {
          if (!ts.isIdentifier(declaration.name)) return false;
          names.push(declaration.name.text);
        }
      }
    }
    if (ts.isExportAssignment(statement)) names.push("default");
    if (ts.isExportDeclaration(statement)) {
      if (statement.moduleSpecifier || !statement.exportClause || !ts.isNamedExports(statement.exportClause)) {
        return false;
      }
      for (const element of statement.exportClause.elements) names.push(element.name.text);
    }
  }
  return names.length === 1 && names[0] === exportedName;
}

function emptyDetailsContract(value) {
  return value && typeof value === "object" && !Array.isArray(value)
    && value.schema === "data_contract.v1" && value.type === "object"
    && value.additional_properties === false
    && Array.isArray(value.required) && value.required.length === 0
    && value.properties && typeof value.properties === "object"
    && !Array.isArray(value.properties) && Object.keys(value.properties).length === 0;
}

function hasForbiddenBundleNode(tree) {
  let rejection = null;
  function visit(node) {
    if (rejection) return;
    if (ts.isImportCall(node) || ts.isAwaitExpression(node) || ts.isNewExpression(node)) {
      rejection = "bundle_dynamic_execution_forbidden";
      return;
    }
    if (ts.isIdentifier(node) && isReferenceIdentifier(node) && forbiddenIdentifiers.has(node.text)) {
      rejection = "bundle_forbidden_identifier";
      return;
    }
    if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
      try {
        const name = propertyName(node);
        if (name !== null && forbiddenProperties.has(name) && name !== "call") rejection = "bundle_forbidden_property";
      } catch (error) {
        // esbuild's fixed export wrapper uses computed property copies; every source
        // module was already checked with the stricter candidate policy.
        if (!(error instanceof Rejection)) throw error;
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  if (rejection) throw new Rejection(rejection);
}

function analyzeCandidate() {
  const kind = String(input.capability_kind || "");
  if (!["presentation", "interaction", "computation"].includes(kind)) throw new Rejection("capability_kind_invalid");
  const modules = Array.isArray(input.javascript_modules) ? input.javascript_modules : [];
  const trees = new Map();
  const sources = new Map();
  for (const item of modules) {
    const path = String(item?.path || "");
    const source = String(item?.source || "");
    if (!path || trees.has(path)) throw new Rejection("javascript_module_invalid", path);
    trees.set(path, parseModule(path, source));
    sources.set(path, source);
  }
  const activation = input.activation && typeof input.activation === "object" ? input.activation : {};
  const entryPath = String(activation.entry_module || "");
  const entrypoint = String(activation.entrypoint || "");
  if (!trees.has(entryPath) || !["render", "mount", "compute", "default"].includes(entrypoint)) {
    throw new Rejection("activation_invalid", entryPath);
  }
  const selectors = new Set(Array.isArray(input.dom_scope?.selectors) ? input.dom_scope.selectors.map(String) : []);
  const classes = new Set(Array.isArray(input.dom_scope?.classes) ? input.dom_scope.classes.map(String) : []);
  const attributes = new Set(Array.isArray(input.dom_scope?.attributes) ? input.dom_scope.attributes.map(String) : []);
  if ([...selectors].some((item) => item.startsWith("#"))) throw new Rejection("id_selector_forbidden");
  const outputEvents = new Set(Object.keys(input.output_contract?.events || {}));
  const redactStrings = Array.isArray(input.redact_strings) ? input.redact_strings.map(String).filter(Boolean) : [];
  const lowerRedactions = redactStrings.map((item) => [item, item.toLocaleLowerCase("en-US")]);
  const functions = functionMap(trees);
  const entryTree = trees.get(entryPath);
  const entryFunctions = new Set();
  let adapterAuthorization = null;
  let adapterCallCount = 0;
  const declaredAdapterV2 = input.candidate_origin === deterministicAdapterOrigin
    && input.adapter_contract_version === computationAdapterV2;
  if (declaredAdapterV2 && (!trees.has(computationCaptureEntry)
      || !trees.has(computationAdapterEntry) || entryPath !== computationAdapterEntry)) {
    throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
  }
  if (trees.has(computationCaptureEntry) && !declaredAdapterV2) {
    throw new Rejection("computation_adapter_authorization_invalid", computationCaptureEntry);
  }

  if (trees.has(computationAdapterEntry) || entryPath === computationAdapterEntry) {
    const adapterV2 = declaredAdapterV2;
    const inputContract = input.input_contract;
    const outputContract = input.output_contract;
    const errorContract = input.error_contract;
    const properties = inputContract?.properties;
    const inputFields = properties && typeof properties === "object" && !Array.isArray(properties)
      ? Object.keys(properties).sort()
      : [];
    const outputProperties = outputContract?.properties;
    const outputFields = outputProperties && typeof outputProperties === "object" && !Array.isArray(outputProperties)
      ? Object.keys(outputProperties)
      : [];
    const errors = errorContract?.errors;
    const errorCodes = errors && typeof errors === "object" && !Array.isArray(errors)
      ? Object.keys(errors).sort()
      : [];
    if (kind !== "computation" || entryPath !== computationAdapterEntry || entrypoint !== "compute"
        || input.activation?.mode !== "declared_input_compute"
        || inputContract?.schema !== "data_contract.v1" || inputContract?.type !== "object"
        || inputContract?.additional_properties !== false || !inputFields.length
        || !Array.isArray(inputContract.required)
        || JSON.stringify([...inputContract.required].sort()) !== JSON.stringify(inputFields)
        || inputFields.some((field) => {
          const contract = properties[field];
          if (!contract || typeof contract !== "object" || Array.isArray(contract)) return true;
          if (contract.type === "integer") {
            return !Number.isSafeInteger(contract.minimum)
              || !Number.isSafeInteger(contract.maximum) || contract.minimum > contract.maximum;
          }
          if (!adapterV2) return true;
          if (contract.type === "boolean") return Object.keys(contract).some((key) => !["type"].includes(key));
          return contract.type !== "string" || !Number.isSafeInteger(contract.min_length)
            || !Number.isSafeInteger(contract.max_length) || contract.min_length < 0
            || contract.min_length > contract.max_length || !Array.isArray(contract.enum)
            || contract.enum.length === 0 || contract.enum.length > 32
            || new Set(contract.enum).size !== contract.enum.length
            || contract.enum.some((value) => typeof value !== "string"
              || value.length < contract.min_length || value.length > contract.max_length);
        })
        || outputContract?.schema !== "data_contract.v1" || outputContract?.type !== "object"
        || outputContract?.additional_properties !== false || outputFields.length !== 1
        || !Array.isArray(outputContract.required) || outputContract.required.length !== 1
        || outputContract.required[0] !== outputFields[0]
        || outputProperties[outputFields[0]]?.type !== "integer"
        || !Number.isSafeInteger(outputProperties[outputFields[0]]?.minimum)
        || !Number.isSafeInteger(outputProperties[outputFields[0]]?.maximum)
        || outputProperties[outputFields[0]].minimum > outputProperties[outputFields[0]].maximum
        || errorContract?.schema !== "error_contract.v1"
        || JSON.stringify(errorCodes) !== JSON.stringify([
          "INPUT_CONTRACT_VIOLATION", "OUTPUT_CONTRACT_VIOLATION",
        ])
        || errorCodes.some((code) => errors[code]?.field !== null
          || !emptyDetailsContract(errors[code]?.details))) {
      throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
    }
    if (adapterV2 && (trees.size !== 2 || !trees.has(computationCaptureEntry))) {
      throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
    }
    if (entryTree.statements.length !== 2) {
      throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
    }
    const importStatement = entryTree.statements[0];
    const computeStatement = entryTree.statements[1];
    const bindings = importStatement?.importClause?.namedBindings;
    if (!ts.isImportDeclaration(importStatement) || importStatement.importClause?.name
        || !bindings || !ts.isNamedImports(bindings) || bindings.elements.length !== 1
        || !ts.isFunctionDeclaration(computeStatement) || computeStatement.name?.text !== "compute"
        || !computeStatement.body || computeStatement.parameters.length !== 1
        || !ts.isIdentifier(computeStatement.parameters[0].name)
        || computeStatement.parameters[0].initializer || computeStatement.parameters[0].dotDotDotToken
        || !computeStatement.modifiers?.some((item) => item.kind === ts.SyntaxKind.ExportKeyword)
        || computeStatement.modifiers?.some((item) => item.kind === ts.SyntaxKind.DefaultKeyword)) {
      throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
    }
    const binding = bindings.elements[0];
    const importedName = binding.propertyName?.text || binding.name.text;
    const localName = binding.name.text;
    const moduleSpecifier = staticString(importStatement.moduleSpecifier) || "";
    const targetPath = resolveRelativeModule(computationAdapterEntry, staticString(importStatement.moduleSpecifier) || "");
    const targetTree = targetPath ? trees.get(targetPath) : null;
    const targetValid = adapterV2
      ? targetPath === computationCaptureEntry && importedName === "__selected"
        && targetTree && hasOnlyNamedExport(targetTree, "__selected")
      : targetTree && exportedFunction(targetTree, importedName);
    if (localName !== "__source" || !targetValid) {
      throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
    }
    const bodyStatements = computeStatement.body.statements;
    const resultStatement = bodyStatements[2];
    const resultDeclarations = ts.isVariableStatement(resultStatement)
      ? resultStatement.declarationList.declarations
      : [];
    const resultDeclaration = resultDeclarations[0];
    const sourceCall = resultDeclaration?.initializer;
    if (bodyStatements.length !== 5 || !ts.isIfStatement(bodyStatements[0])
        || !ts.isIfStatement(bodyStatements[1]) || !ts.isVariableStatement(resultStatement)
        || !(resultStatement.declarationList.flags & ts.NodeFlags.Const)
        || resultDeclarations.length !== 1 || !ts.isIdentifier(resultDeclaration?.name)
        || resultDeclaration.name.text !== "result" || !ts.isCallExpression(sourceCall)
        || !ts.isIdentifier(sourceCall.expression) || sourceCall.expression.text !== localName
        || !ts.isIfStatement(bodyStatements[3]) || !ts.isReturnStatement(bodyStatements[4])) {
      throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
    }
    const mappedFields = [];
    for (const argument of sourceCall.arguments) {
      if (!ts.isPropertyAccessExpression(argument) || argument.questionDotToken
          || !ts.isIdentifier(argument.expression)
          || argument.expression.text !== computeStatement.parameters[0].name.text) {
        throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
      }
      mappedFields.push(argument.name.text);
    }
    if (mappedFields.length !== inputFields.length || new Set(mappedFields).size !== mappedFields.length
        || [...mappedFields].sort().join("\0") !== inputFields.join("\0")) {
      throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
    }
    const inputName = computeStatement.parameters[0].name.text;
    const inputShapeChecks = [
      `${inputName} === null`,
      `typeof ${inputName} !== "object"`,
      `Array.isArray(${inputName})`,
      `Object.keys(${inputName}).length !== ${inputFields.length}`,
      ...mappedFields.map((field) => `!Object.hasOwn(${inputName}, ${JSON.stringify(field)})`),
    ];
    const inputValueChecks = mappedFields.flatMap((field) => {
      const contract = properties[field];
      if (contract.type === "integer") return [
        `!Number.isSafeInteger(${inputName}.${field})`,
        `${inputName}.${field} < ${contract.minimum}`,
        `${inputName}.${field} > ${contract.maximum}`,
      ];
      if (contract.type === "boolean") return [`typeof ${inputName}.${field} !== "boolean"`];
      return [
        `typeof ${inputName}.${field} !== "string"`,
        `(${contract.enum.map((value) => `${inputName}.${field} !== ${JSON.stringify(value)}`).join(" && ")})`,
      ];
    });
    const outputField = outputFields[0];
    const outputValue = outputProperties[outputField];
    const inputError = '    return { ok: false, error: { code: "INPUT_CONTRACT_VIOLATION", field: null, details: {} } };';
    const outputError = '    return { ok: false, error: { code: "OUTPUT_CONTRACT_VIOLATION", field: null, details: {} } };';
    const expectedSource = [
      `import { ${importedName} as __source } from ${JSON.stringify(moduleSpecifier)};`,
      "",
      `export function compute(${inputName}) {`,
      "  if (",
      `    ${inputShapeChecks.join("\n    || ")}`,
      "  ) {",
      inputError,
      "  }",
      "  if (",
      `    ${inputValueChecks.join("\n    || ")}`,
      "  ) {",
      inputError,
      "  }",
      `  const result = __source(${mappedFields.map((field) => `${inputName}.${field}`).join(", ")});`,
      "  if (",
      "    !Number.isSafeInteger(result)",
      `    || result < ${outputValue.minimum}`,
      `    || result > ${outputValue.maximum}`,
      "  ) {",
      outputError,
      "  }",
      `  return { ok: true, value: { ${JSON.stringify(outputField)}: result } };`,
      "}",
      "",
    ].join("\n");
    if (sources.get(computationAdapterEntry) !== expectedSource) {
      throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
    }
    adapterAuthorization = {
      fn: computeStatement,
      inputName,
      inputFields,
      sourceBinding: localName,
    };
  }
  function addEntrypoint(name) {
    const target = functions.get(`${entryPath}:${name}`);
    if (target) entryFunctions.add(target);
  }
  for (const statement of entryTree.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.body) {
      const directName = statement.name?.text;
      const directExport = statement.modifiers?.some((item) => item.kind === ts.SyntaxKind.ExportKeyword);
      const defaultExport = statement.modifiers?.some((item) => item.kind === ts.SyntaxKind.DefaultKeyword);
      if (directExport && (directName === entrypoint || (entrypoint === "default" && defaultExport))) {
        entryFunctions.add(statement);
      }
    }
    if (ts.isVariableStatement(statement)
        && statement.modifiers?.some((item) => item.kind === ts.SyntaxKind.ExportKeyword)) {
      for (const declaration of statement.declarationList.declarations) {
        if (ts.isIdentifier(declaration.name) && declaration.name.text === entrypoint
            && declaration.initializer
            && (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer))) {
          entryFunctions.add(declaration.initializer);
        }
      }
    }
    if (entrypoint === "default" && ts.isExportAssignment(statement)
        && !statement.isExportEquals && ts.isIdentifier(statement.expression)) {
      addEntrypoint(statement.expression.text);
    }
    if (ts.isExportDeclaration(statement) && statement.exportClause
        && ts.isNamedExports(statement.exportClause)) {
      for (const item of statement.exportClause.elements) {
        if (item.name.text === entrypoint) addEntrypoint(item.propertyName?.text || item.name.text);
      }
    }
  }
  const replacements = new Map();
  const listenerEvidence = [];

  function addReplacement(path, node, structural) {
    const value = staticString(node);
    if (value === null) return;
    let cleaned = value;
    let changed = false;
    for (const [raw, folded] of lowerRedactions) {
      if (!folded || !cleaned.toLocaleLowerCase("en-US").includes(folded)) continue;
      if (structural) throw new Rejection("redaction_in_structural_string", path);
      const pattern = raw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      cleaned = cleaned.replace(new RegExp(pattern, "giu"), "[REDACTED]");
      changed = true;
    }
    if (changed) {
      const rows = replacements.get(path) || [];
      const replacement = { start: node.getStart(trees.get(path)), end: node.getEnd(), value: JSON.stringify(cleaned) };
      if (!rows.some((item) => item.start === replacement.start && item.end === replacement.end)) rows.push(replacement);
      replacements.set(path, rows);
    }
  }

  function analyzeFunction(
    path,
    fn,
    inherited,
    domBindings,
    eventParam = null,
    moduleVariables = new Set(),
    inheritedFunctions = new Map(),
    inheritedProtectedKinds = new Map(),
  ) {
    if (fn.asteriskToken || fn.modifiers?.some((item) => item.kind === ts.SyntaxKind.AsyncKeyword)) {
      throw new Rejection("async_or_generator_forbidden", path);
    }
    const names = new Set(inherited);
    collectNames(fn, names);
    const params = fn.parameters.filter((item) => ts.isIdentifier(item.name)).map((item) => item.name.text);
    for (const name of params) names.add(name);
    const protectedKinds = new Map(inheritedProtectedKinds);
    if (entryFunctions.has(fn)) {
      if (fn.parameters.some((item) => !ts.isIdentifier(item.name))) {
        throw new Rejection("protected_reference_destructuring_forbidden", path);
      }
      if (kind === "computation" && params[0]) protectedKinds.set(params[0], "input");
      if (kind === "presentation") {
        if (params[0]) protectedKinds.set(params[0], "root");
        if (params[1]) protectedKinds.set(params[1], "input");
      }
      if (kind === "interaction") {
        if (params[0]) protectedKinds.set(params[0], "root");
        if (params[1]) protectedKinds.set(params[1], "ports");
      }
    }
    const localFunctions = new Map(inheritedFunctions);
    function collectLocalFunctions(node) {
      if (node !== fn && ts.isFunctionLike(node)) {
        if (ts.isFunctionDeclaration(node) && node.name) localFunctions.set(node.name.text, node);
        if ((ts.isArrowFunction(node) || ts.isFunctionExpression(node))
            && ts.isVariableDeclaration(node.parent) && ts.isIdentifier(node.parent.name)) {
          localFunctions.set(node.parent.name.text, node);
        }
        return;
      }
      ts.forEachChild(node, collectLocalFunctions);
    }
    collectLocalFunctions(fn.body);
    let opaqueEvent = eventParam;
    function findPreventDefault(node) {
      if (node !== fn && ts.isFunctionLike(node)) return;
      if (ts.isCallExpression(node) && (ts.isPropertyAccessExpression(node.expression)
          || ts.isElementAccessExpression(node.expression)) && propertyName(node.expression) === "preventDefault") {
        const owner = rootIdentifier(node.expression.expression);
        if (params.includes(owner)) {
          if (opaqueEvent && opaqueEvent !== owner) throw new Rejection("multiple_event_objects_forbidden", path);
          opaqueEvent = owner;
        }
      }
      ts.forEachChild(node, findPreventDefault);
    }
    findPreventDefault(fn.body);

    function protectedReferences(node) {
      if (!node) return new Set();
      if (ts.isParenthesizedExpression(node)) return protectedReferences(node.expression);
      if (ts.isFunctionLike(node)) return new Set();
      if (ts.isIdentifier(node)) {
        if (opaqueEvent && node.text === opaqueEvent) return new Set(["event"]);
        if (domBindings.has(node.text)) return new Set(["dom"]);
        const protectedKind = protectedKinds.get(node.text);
        return protectedKind ? new Set([protectedKind]) : new Set();
      }
      if (ts.isCallExpression(node)) {
        const result = new Set();
        if (ts.isPropertyAccessExpression(node.expression)
            || ts.isElementAccessExpression(node.expression)) {
          const receiverReferences = protectedReferences(node.expression.expression);
          const method = propertyName(node.expression);
          if (["querySelector", "querySelectorAll"].includes(method)
              && receiverReferences.has("root")) {
            return new Set(["dom"]);
          }
          for (const base of receiverReferences) result.add(`${base}_derived`);
        }
        for (const argument of node.arguments) {
          for (const base of protectedReferences(argument)) result.add(base);
        }
        return result;
      }
      if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
        const result = new Set();
        const name = propertyName(node);
        for (const base of protectedReferences(node.expression)) {
          if (base === "dom" && allowedDomRead.has(name)) continue;
          if (base === "input" || base === "input_value" || base === "ports_input") {
            result.add("input_value");
          } else if (base === "ports" && name === "input") {
            result.add("ports_input");
          } else {
            result.add(`${base}_derived`);
          }
        }
        return result;
      }
      if (ts.isObjectLiteralExpression(node)) {
        const result = new Set();
        for (const property of node.properties) {
          let value = null;
          if (ts.isShorthandPropertyAssignment(property)) value = property.name;
          if (ts.isPropertyAssignment(property)) value = property.initializer;
          if (ts.isSpreadAssignment(property)) value = property.expression;
          for (const item of protectedReferences(value)) result.add(item);
        }
        return result;
      }
      if (ts.isArrayLiteralExpression(node)) {
        const result = new Set();
        for (const element of node.elements) {
          const value = ts.isSpreadElement(element) ? element.expression : element;
          for (const item of protectedReferences(value)) result.add(item);
        }
        return result;
      }
      if (ts.isConditionalExpression(node)) {
        return new Set([
          ...protectedReferences(node.whenTrue),
          ...protectedReferences(node.whenFalse),
        ]);
      }
      if (ts.isBinaryExpression(node)) {
        return new Set([
          ...protectedReferences(node.left),
          ...protectedReferences(node.right),
        ]);
      }
      const result = new Set();
      ts.forEachChild(node, (child) => {
        for (const item of protectedReferences(child)) result.add(item);
      });
      return result;
    }

    function rejectProtectedArguments(args, allowed = new Set()) {
      for (const argument of args) {
        const references = protectedReferences(argument);
        if ([...references].some((item) => !allowed.has(item))) {
          throw new Rejection("protected_reference_argument_forbidden", path);
        }
      }
    }

    function isDirectPreventDefaultReceiver(node) {
      const access = node.parent;
      if (!ts.isPropertyAccessExpression(access) || access.expression !== node
          || access.name.text !== "preventDefault" || access.questionDotToken) return false;
      const call = access.parent;
      return ts.isCallExpression(call) && call.expression === access
        && !call.questionDotToken && call.arguments.length === 0;
    }

    function visit(node) {
      if (node !== fn && ts.isFunctionLike(node)) {
        const capturedProtectedKinds = new Map(protectedKinds);
        if (opaqueEvent) capturedProtectedKinds.set(opaqueEvent, "event");
        analyzeFunction(
          path,
          node,
          names,
          domBindings,
          null,
          moduleVariables,
          localFunctions,
          capturedProtectedKinds,
        );
        return;
      }
      if (ts.isAwaitExpression(node) || ts.isYieldExpression(node) || ts.isNewExpression(node)
          || ts.isDeleteExpression(node) || node.kind === ts.SyntaxKind.ThisKeyword
          || node.kind === ts.SyntaxKind.SuperKeyword) {
        throw new Rejection("dynamic_or_context_execution_forbidden", path);
      }
      if (ts.isIdentifier(node) && isReferenceIdentifier(node)) {
        const eventReference = (opaqueEvent && node.text === opaqueEvent)
          || protectedKinds.get(node.text) === "event";
        if (eventReference && !(opaqueEvent === node.text && isDirectPreventDefaultReceiver(node))) {
          throw new Rejection("event_object_property_forbidden", path);
        }
        if (forbiddenIdentifiers.has(node.text)) throw new Rejection("forbidden_identifier", path);
        if (!names.has(node.text) && !allowedGlobals.has(node.text)) throw new Rejection("unknown_global_identifier", path);
      }
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer
          && ts.isCallExpression(node.initializer) && (ts.isPropertyAccessExpression(node.initializer.expression)
          || ts.isElementAccessExpression(node.initializer.expression))) {
        const call = node.initializer;
        const method = propertyName(call.expression);
        if (method === "querySelector" || method === "querySelectorAll") {
          const owner = call.expression.expression;
          const rootName = params[0];
          const selector = staticString(call.arguments[0]);
          if (!ts.isIdentifier(owner) || owner.text !== rootName || call.arguments.length !== 1 || selector === null || !selectors.has(selector)) {
            throw new Rejection("dom_query_outside_scope", path);
          }
          addReplacement(path, call.arguments[0], true);
          domBindings.set(node.name.text, selector);
        }
      }
      if (ts.isVariableDeclaration(node) && node.initializer) {
        const declaredDomBinding = ts.isIdentifier(node.name)
          && domBindings.has(node.name.text)
          && ts.isCallExpression(node.initializer)
          && (ts.isPropertyAccessExpression(node.initializer.expression)
            || ts.isElementAccessExpression(node.initializer.expression))
          && ["querySelector", "querySelectorAll"].includes(
            propertyName(node.initializer.expression),
          );
        if (!ts.isIdentifier(node.name) && ts.isCallExpression(node.initializer)
            && (ts.isPropertyAccessExpression(node.initializer.expression)
              || ts.isElementAccessExpression(node.initializer.expression))
            && ["querySelector", "querySelectorAll"].includes(propertyName(node.initializer.expression))) {
          throw new Rejection("protected_reference_destructuring_forbidden", path);
        }
        const initializerReferences = protectedReferences(node.initializer);
        if ([...initializerReferences].some((item) => item.startsWith("event_"))) {
          throw new Rejection("event_object_property_forbidden", path);
        }
        if (!declaredDomBinding
            && [...initializerReferences].some((item) => item !== "input_value")) {
          throw new Rejection(
            ts.isIdentifier(node.name)
              ? "protected_reference_alias_forbidden"
              : "protected_reference_destructuring_forbidden",
            path,
          );
        }
        if (ts.isIdentifier(node.name)
            && initializerReferences.size
            && [...initializerReferences].every((item) => item === "input_value")) {
          protectedKinds.set(node.name.text, "input_value");
        }
      }
      if (ts.isParameter(node) && node.initializer && protectedReferences(node.initializer).size) {
        throw new Rejection("protected_reference_argument_forbidden", path);
      }
      if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
        const name = propertyName(node);
        if (forbiddenProperties.has(name)) throw new Rejection("forbidden_property", path);
        const owner = rootIdentifier(node);
        if (opaqueEvent && owner === opaqueEvent && name !== "preventDefault") {
          throw new Rejection("event_object_property_forbidden", path);
        }
        if (domBindings.has(owner) && !allowedDomRead.has(name) && name !== "classList"
            && !allowedDomMethods.has(name) && !["add", "remove", "toggle"].includes(name)) {
          throw new Rejection("dom_read_forbidden", path);
        }
      }
      if (ts.isBinaryExpression(node) && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment
          && node.operatorToken.kind <= ts.SyntaxKind.LastAssignment) {
        const rightReferences = protectedReferences(node.right);
        if ([...rightReferences].some((item) => item !== "input_value")) {
          throw new Rejection("protected_reference_alias_forbidden", path);
        }
        if (ts.isIdentifier(node.left) && rightReferences.has("input_value")
            && !protectedKinds.has(node.left.text)) {
          throw new Rejection("protected_reference_alias_forbidden", path);
        }
        if (ts.isIdentifier(node.left)
            && (protectedKinds.has(node.left.text) || domBindings.has(node.left.text)
              || (opaqueEvent && node.left.text === opaqueEvent))) {
          throw new Rejection("protected_reference_assignment_forbidden", path);
        }
        if (ts.isIdentifier(node.left) && moduleVariables.has(node.left.text)) {
          throw new Rejection("module_state_mutation_forbidden", path);
        }
        if (ts.isPropertyAccessExpression(node.left) || ts.isElementAccessExpression(node.left)) {
          const owner = rootIdentifier(node.left);
          const name = propertyName(node.left);
          const directOwner = ts.isIdentifier(node.left.expression)
            ? node.left.expression.text
            : null;
          const ownerReferences = protectedReferences(node.left.expression);
          const targetsScopedDom = [...ownerReferences].some(
            (item) => item === "root" || item === "dom"
              || item.startsWith("root_") || item.startsWith("dom_"),
          );
          if (params.includes(owner) || owner === "input" || owner === "ports") throw new Rejection("input_mutation_forbidden", path);
          if (allowedGlobals.has(owner)) throw new Rejection("global_object_mutation_forbidden", path);
          if (targetsScopedDom) {
            if (!directOwner || !domBindings.has(directOwner)
                || !allowedDomWrite.has(name)) {
              throw new Rejection("dom_write_forbidden", path);
            }
          } else if (domBindings.has(owner)) {
            if (!allowedDomWrite.has(name)) throw new Rejection("dom_write_forbidden", path);
          } else if (kind !== "interaction") {
            throw new Rejection("object_state_mutation_forbidden", path);
          }
        }
      }
      if ((ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node))
          && [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(node.operator)
          && ts.isIdentifier(node.operand)) {
        if (protectedKinds.has(node.operand.text) || domBindings.has(node.operand.text)
            || (opaqueEvent && node.operand.text === opaqueEvent)) {
          throw new Rejection("protected_reference_assignment_forbidden", path);
        }
        if (moduleVariables.has(node.operand.text)) throw new Rejection("module_state_mutation_forbidden", path);
      }
      if (ts.isReturnStatement(node) && node.expression
          && !ts.isArrowFunction(node.expression) && !ts.isFunctionExpression(node.expression)) {
        const references = protectedReferences(node.expression);
        if ([...references].some((item) => item !== "input_value")) {
          throw new Rejection("protected_reference_return_forbidden", path);
        }
      }
      if (ts.isCallExpression(node)) validateCall(path, node, names, params, domBindings, opaqueEvent);
      if (ts.isStringLiteralLike(node)) addReplacement(path, node, false);
      ts.forEachChild(node, visit);
    }

    function validateCall(pathValue, call, localNames, functionParams, bindings, currentEventParam) {
      if (call.expression.kind === ts.SyntaxKind.ImportKeyword) throw new Rejection("dynamic_import_forbidden", pathValue);
      if (ts.isIdentifier(call.expression)) {
        const name = call.expression.text;
        if (forbiddenIdentifiers.has(name)) throw new Rejection("forbidden_call", pathValue);
        const primitiveConversions = new Set(["Boolean", "Number", "String", "parseFloat", "parseInt"]);
        if (primitiveConversions.has(name)) {
          rejectProtectedArguments(call.arguments, new Set(["input_value"]));
          return;
        }
        if (adapterAuthorization && pathValue === computationAdapterEntry
            && fn === adapterAuthorization.fn && name === adapterAuthorization.sourceBinding) {
          const fields = [];
          for (const argument of call.arguments) {
            if (!ts.isPropertyAccessExpression(argument) || argument.questionDotToken
                || !ts.isIdentifier(argument.expression)
                || argument.expression.text !== adapterAuthorization.inputName) {
              throw new Rejection("computation_adapter_argument_forbidden", pathValue);
            }
            fields.push(argument.name.text);
          }
          if (fields.length !== adapterAuthorization.inputFields.length
              || new Set(fields).size !== fields.length
              || [...fields].sort().join("\0") !== adapterAuthorization.inputFields.join("\0")) {
            throw new Rejection("computation_adapter_argument_forbidden", pathValue);
          }
          adapterCallCount += 1;
          return;
        }
        rejectProtectedArguments(call.arguments);
        if (!localNames.has(name)) {
          throw new Rejection("unknown_call_target", pathValue);
        }
        return;
      }
      if (!ts.isPropertyAccessExpression(call.expression) && !ts.isElementAccessExpression(call.expression)) {
        throw new Rejection("unknown_call_target", pathValue);
      }
      const ownerNode = call.expression.expression;
      const owner = rootIdentifier(ownerNode);
      const method = propertyName(call.expression);
      if (forbiddenProperties.has(method)) throw new Rejection("forbidden_call", pathValue);
      const inAdapterEntrypoint = adapterAuthorization
        && pathValue === computationAdapterEntry && fn === adapterAuthorization.fn;
      if (inAdapterEntrypoint && ts.isIdentifier(ownerNode)
          && ownerNode.text === "Array" && method === "isArray"
          && call.arguments.length === 1 && ts.isIdentifier(call.arguments[0])
          && call.arguments[0].text === adapterAuthorization.inputName) {
        return;
      }
      if (inAdapterEntrypoint && ts.isIdentifier(ownerNode)
          && ownerNode.text === "Object" && method === "hasOwn"
          && call.arguments.length === 2 && ts.isIdentifier(call.arguments[0])
          && call.arguments[0].text === adapterAuthorization.inputName) {
        const field = staticString(call.arguments[1]);
        if (!field || !adapterAuthorization.inputFields.includes(field)) {
          throw new Rejection("computation_adapter_argument_forbidden", pathValue);
        }
        return;
      }
      if (inAdapterEntrypoint && ts.isIdentifier(ownerNode)
          && ownerNode.text === "Number" && method === "isSafeInteger"
          && call.arguments.length === 1) {
        return;
      }
      if (ts.isIdentifier(ownerNode) && ownerNode.text === "Math" && allowedMathMethods.has(method)) {
        rejectProtectedArguments(call.arguments, new Set(["input_value"]));
        return;
      }
      if (ts.isIdentifier(ownerNode) && ownerNode.text === "Number" && allowedNumberMethods.has(method)) {
        rejectProtectedArguments(call.arguments, new Set(["input_value"]));
        return;
      }
      if (ts.isIdentifier(ownerNode) && ownerNode.text === "JSON" && allowedJsonMethods.has(method)) {
        rejectProtectedArguments(call.arguments, new Set(["input_value"]));
        return;
      }
      if (ts.isIdentifier(ownerNode) && ownerNode.text === "Object" && allowedObjectMethods.has(method)) {
        rejectProtectedArguments(call.arguments, new Set(["input", "input_value"]));
        return;
      }
      if ([...allowedArrayMethods, ...allowedStringMethods].includes(method)) {
        rejectProtectedArguments(call.arguments, new Set(["input_value"]));
        return;
      }
      if (method === "querySelector" || method === "querySelectorAll") {
        const selector = staticString(call.arguments[0]);
        if (!ts.isIdentifier(ownerNode) || ownerNode.text !== functionParams[0]
            || call.arguments.length !== 1 || selector === null || !selectors.has(selector)) {
          throw new Rejection("dom_query_outside_scope", pathValue);
        }
        return;
      }
      if (["addEventListener", "removeEventListener"].includes(method)) {
        if (kind !== "interaction" || !bindings.has(owner) || call.arguments.length !== 2) throw new Rejection("event_binding_forbidden", pathValue);
        const event = staticString(call.arguments[0]);
        const handler = call.arguments[1];
        if (!event || !allowedEvents.has(event) || !input.dom_scope.events?.includes(event) || !ts.isIdentifier(handler)) {
          throw new Rejection("event_binding_forbidden", pathValue);
        }
        const handlerFunction = localFunctions.get(handler.text) || functions.get(`${pathValue}:${handler.text}`);
        if (!handlerFunction || handlerFunction === fn
            || (handlerFunction.parameters[0]
              && !ts.isIdentifier(handlerFunction.parameters[0].name))) {
          throw new Rejection("event_handler_must_be_local", pathValue);
        }
        const eventParameter = handlerFunction.parameters[0]?.name.text || null;
        analyzeFunction(
          pathValue,
          handlerFunction,
          localNames,
          bindings,
          eventParameter,
          moduleVariables,
          localFunctions,
          protectedKinds,
        );
        addReplacement(pathValue, call.arguments[0], true);
        listenerEvidence.push({ selector: bindings.get(owner), event, handler: handler.text, operation: method });
        return;
      }
      if (method === "emit") {
        if (kind !== "interaction" || !localNames.has(owner) || call.arguments.length !== 2) throw new Rejection("emit_forbidden", pathValue);
        const event = staticString(call.arguments[0]);
        if (!event || !outputEvents.has(event)) throw new Rejection("undeclared_emit", pathValue);
        rejectProtectedArguments([call.arguments[1]], new Set(["input_value"]));
        addReplacement(pathValue, call.arguments[0], true);
        return;
      }
      if (method === "preventDefault") {
        if (!currentEventParam || owner !== currentEventParam || call.arguments.length !== 0) throw new Rejection("event_object_property_forbidden", pathValue);
        return;
      }
      if (["add", "remove", "toggle"].includes(method) && propertyName(ownerNode) === "classList") {
        if (!bindings.has(rootIdentifier(ownerNode)) || call.arguments.some((item) => staticString(item) === null || !classes.has(staticString(item)))) {
          throw new Rejection("undeclared_class_mutation", pathValue);
        }
        for (const item of call.arguments) addReplacement(pathValue, item, true);
        return;
      }
      if (["setAttribute", "removeAttribute"].includes(method)) {
        const name = staticString(call.arguments[0]);
        if (!bindings.has(owner) || !name || !attributes.has(name) || (method === "setAttribute" && call.arguments.length !== 2)) {
          throw new Rejection("undeclared_attribute_mutation", pathValue);
        }
        rejectProtectedArguments(call.arguments.slice(1), new Set(["input_value"]));
        addReplacement(pathValue, call.arguments[0], true);
        return;
      }
      if (["append", "replaceChildren"].includes(method) && bindings.has(owner)) {
        rejectProtectedArguments(call.arguments);
        return;
      }
      if (method === "cloneNode") throw new Rejection("clone_node_template_evidence_required", pathValue);
      throw new Rejection("unknown_call_target", pathValue);
    }

    if (ts.isArrowFunction(fn) && !ts.isBlock(fn.body)) {
      const references = protectedReferences(fn.body);
      if ([...references].some((item) => item !== "input_value")) {
        throw new Rejection("protected_reference_return_forbidden", path);
      }
    }
    visit(fn.body);
  }

  for (const [path, tree] of trees) {
    const names = moduleNames(tree);
    const moduleVariables = moduleVariableNames(tree);
    const staticScalarNames = moduleStaticScalarNames(tree);
    for (const name of forbiddenIdentifiers) if (names.has(name)) throw new Rejection("forbidden_identifier_shadow", path);
    for (const statement of tree.statements) {
      if (ts.isImportDeclaration(statement)) {
        const specifier = staticString(statement.moduleSpecifier);
        if (!statement.importClause || !specifier || !specifier.startsWith(".")
            || statement.assertClause || statement.attributes) {
          throw new Rejection("module_import_forbidden", path);
        }
        continue;
      }
      if (ts.isExportDeclaration(statement)) {
        if (!statement.exportClause || statement.moduleSpecifier) throw new Rejection("module_export_forbidden", path);
        continue;
      }
      if (ts.isVariableStatement(statement) && kind === "computation") {
        for (const declaration of statement.declarationList.declarations) {
          if (declaration.initializer && (ts.isArrayLiteralExpression(declaration.initializer) || ts.isObjectLiteralExpression(declaration.initializer))) {
            throw new Rejection("module_state_forbidden", path);
          }
        }
      }
      if (!ts.isFunctionDeclaration(statement) && !ts.isVariableStatement(statement)
          && !ts.isExportAssignment(statement) && !ts.isEmptyStatement(statement)) {
        throw new Rejection("module_top_level_execution_forbidden", path);
      }
      if (ts.isFunctionDeclaration(statement) && statement.body) analyzeFunction(path, statement, names, new Map(), null, moduleVariables);
      if (ts.isVariableStatement(statement)) {
        for (const declaration of statement.declarationList.declarations) {
          if (declaration.initializer && (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer))) {
            analyzeFunction(path, declaration.initializer, names, new Map(), null, moduleVariables);
          } else if (declaration.initializer) {
            function inspectInitializer(node) {
              if (ts.isIdentifier(node) && isReferenceIdentifier(node)) {
                if (forbiddenIdentifiers.has(node.text)) throw new Rejection("forbidden_identifier", path);
                if (!names.has(node.text) && !allowedGlobals.has(node.text)) throw new Rejection("unknown_global_identifier", path);
              }
              if (ts.isCallExpression(node)) {
                const allowedCaptureInitializer = declaredAdapterV2
                  && path === computationCaptureEntry
                  && node === declaration.initializer
                  && ts.isIdentifier(node.expression)
                  && functions.has(`${path}:${node.expression.text}`)
                  && node.arguments.every((argument) => staticCaptureArgument(argument, staticScalarNames));
                if (!allowedCaptureInitializer) {
                  throw new Rejection("module_top_level_execution_forbidden", path);
                }
                return;
              }
              if (ts.isNewExpression(node) || ts.isAwaitExpression(node)) throw new Rejection("module_top_level_execution_forbidden", path);
              if (ts.isStringLiteralLike(node)) addReplacement(path, node, false);
              ts.forEachChild(node, inspectInitializer);
            }
            inspectInitializer(declaration.initializer);
          }
        }
      }
      if (ts.isExportAssignment(statement)) {
        if (statement.isExportEquals || !ts.isIdentifier(statement.expression) || !names.has(statement.expression.text)) {
          throw new Rejection("module_export_forbidden", path);
        }
      }
    }
  }

  let entryExportFound = false;
  for (const statement of entryTree.statements) {
    if (entrypoint === "default" && ts.isExportAssignment(statement) && !statement.isExportEquals) entryExportFound = true;
    if (entrypoint === "default" && ts.isFunctionDeclaration(statement)
        && statement.modifiers?.some((item) => item.kind === ts.SyntaxKind.ExportKeyword)
        && statement.modifiers?.some((item) => item.kind === ts.SyntaxKind.DefaultKeyword)) entryExportFound = true;
    if (ts.isFunctionDeclaration(statement) && statement.name?.text === entrypoint
        && statement.modifiers?.some((item) => item.kind === ts.SyntaxKind.ExportKeyword)) entryExportFound = true;
    if (ts.isVariableStatement(statement)
        && statement.modifiers?.some((item) => item.kind === ts.SyntaxKind.ExportKeyword)
        && statement.declarationList.declarations.some((item) => ts.isIdentifier(item.name) && item.name.text === entrypoint)) {
      entryExportFound = true;
    }
    if (ts.isExportDeclaration(statement) && statement.exportClause && ts.isNamedExports(statement.exportClause)) {
      for (const item of statement.exportClause.elements) {
        if (item.name.text === entrypoint || entrypoint === "default" && item.name.text === "default") entryExportFound = true;
      }
    }
  }
  if (!entryExportFound) throw new Rejection("entrypoint_export_missing", entryPath);
  if (adapterAuthorization && adapterCallCount !== 1) {
    throw new Rejection("computation_adapter_authorization_invalid", computationAdapterEntry);
  }

  // Event handlers are analyzed again with their event parameter marked as opaque.
  for (const [path, tree] of trees) {
    const names = moduleNames(tree);
    const moduleVariables = moduleVariableNames(tree);
    const bindings = new Map();
    function findListeners(node) {
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer
          && ts.isCallExpression(node.initializer) && ts.isPropertyAccessExpression(node.initializer.expression)
          && ["querySelector", "querySelectorAll"].includes(node.initializer.expression.name.text)) {
        const selector = staticString(node.initializer.arguments[0]);
        if (selector && selectors.has(selector)) bindings.set(node.name.text, selector);
      }
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
          && node.expression.name.text === "addEventListener" && ts.isIdentifier(node.arguments[1])) {
        const event = staticString(node.arguments[0]);
        const handler = functions.get(`${path}:${node.arguments[1].text}`);
        if (handler && handler.parameters[0] && ts.isIdentifier(handler.parameters[0].name)) {
          const eventName = handler.parameters[0].name.text;
          analyzeFunction(path, handler, names, bindings, eventName, moduleVariables);
          if (event === "submit") {
            let prevented = false;
            function findPrevention(current) {
              if (current !== handler && ts.isFunctionLike(current)) return;
              if (ts.isCallExpression(current) && ts.isPropertyAccessExpression(current.expression)
                  && current.expression.name.text === "preventDefault"
                  && ts.isIdentifier(current.expression.expression)
                  && current.expression.expression.text === eventName) prevented = true;
              ts.forEachChild(current, findPrevention);
            }
            findPrevention(handler.body);
            if (!prevented) throw new Rejection("submit_prevent_default_required", path);
          }
        }
      }
      ts.forEachChild(node, findListeners);
    }
    findListeners(tree);
  }

  const cleanedModules = [];
  for (const item of modules) {
    const path = String(item.path);
    let source = sources.get(path);
    for (const row of (replacements.get(path) || []).sort((left, right) => right.start - left.start)) {
      source = `${source.slice(0, row.start)}${row.value}${source.slice(row.end)}`;
    }
    cleanedModules.push({ path, source: source.replace(/\r\n?/g, "\n") });
  }
  const sensitivityLiteralsByPath = {};
  for (const item of cleanedModules) {
    const values = new Set();
    const tree = parseModule(item.path, item.source);
    function collect(node) {
      if (ts.isStringLiteralLike(node)) values.add(node.text);
      else if (ts.isNumericLiteral(node)) {
        const value = Number(node.text);
        if (Number.isSafeInteger(value)) values.add(String(value));
      }
      ts.forEachChild(node, collect);
    }
    collect(tree);
    sensitivityLiteralsByPath[item.path] = [...values].sort((left, right) =>
      Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8"))
    );
  }
  const added = listenerEvidence.filter((item) => item.operation === "addEventListener").map(({ selector, event, handler }) => ({ selector, event, handler }));
  const removed = new Set(listenerEvidence.filter((item) => item.operation === "removeEventListener").map((item) => `${item.selector}\0${item.event}\0${item.handler}`));
  if (added.some((item) => !removed.has(`${item.selector}\0${item.event}\0${item.handler}`))) throw new Rejection("interaction_dispose_not_closed");
  if (kind === "presentation" && added.length) throw new Rejection("presentation_event_binding_forbidden");
  return {
    schema_version: "javascript_security.v1",
    status: "passed",
    javascript_modules: cleanedModules,
    listener_bindings: [...new Map(added.map((item) => [`${item.selector}\0${item.event}\0${item.handler}`, item])).values()],
    sensitivity_literals_by_path: sensitivityLiteralsByPath,
  };
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value && typeof value === "object") {
    const result = {};
    for (const key of Object.keys(value).sort()) result[key] = canonicalValue(value[key]);
    return result;
  }
  return value;
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

async function buildExecutionBundleV2() {
  const modules = Array.isArray(input.javascript_modules) ? input.javascript_modules : [];
  const sources = new Map();
  for (const item of modules) {
    const logicalPath = String(item?.path || "");
    const source = String(item?.source || "");
    if (!logicalPath || sources.has(logicalPath)) throw new Rejection("execution_bundle_input_invalid");
    sources.set(logicalPath, source);
  }
  if (sources.size !== 2 || !sources.has(computationCaptureEntry) || !sources.has(computationAdapterEntry)) {
    throw new Rejection("execution_bundle_input_invalid");
  }
  const plugin = {
    name: "reweave-snapshot-only",
    setup(buildApi) {
      buildApi.onResolve({ filter: /.*/ }, (args) => {
        if (args.kind === "entry-point") {
          return args.path === computationAdapterEntry
            ? { path: computationAdapterEntry, namespace: "reweave-snapshot" }
            : { errors: [{ text: "execution_bundle_entry_invalid" }] };
        }
        if (args.namespace !== "reweave-snapshot" || (args.path !== "../__reweave_capture__/selected.js")) {
          return { errors: [{ text: "execution_bundle_resolution_invalid" }] };
        }
        return { path: computationCaptureEntry, namespace: "reweave-snapshot" };
      });
      buildApi.onLoad({ filter: /.*/, namespace: "reweave-snapshot" }, (args) => {
        if (!sources.has(args.path)) return { errors: [{ text: "execution_bundle_module_missing" }] };
        return { contents: sources.get(args.path), loader: "js", resolveDir: "/__reweave_execution__" };
      });
    },
  };
  const options = {
    bundle: true,
    treeShaking: true,
    format: "iife",
    globalName: "ReweaveCandidate",
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
  };
  const requestedRoot = typeof input.temporary_root === "string"
    ? input.temporary_root
    : "";
  if (!path.isAbsolute(requestedRoot)) throw new Rejection("execution_bundle_failed");
  let requestedStat;
  let requestedReal;
  try {
    requestedStat = await fs.lstat(requestedRoot);
    requestedReal = await fs.realpath(requestedRoot);
  } catch {
    throw new Rejection("execution_bundle_failed");
  }
  if (!requestedStat.isDirectory() || requestedStat.isSymbolicLink()
      || requestedReal !== requestedRoot
      || (typeof process.getuid === "function" && requestedStat.uid !== process.getuid())
      || (process.platform !== "win32" && (requestedStat.mode & 0o077) !== 0)) {
    throw new Rejection("execution_bundle_failed");
  }
  let marker;
  try {
    marker = await fs.readFile(path.join(requestedRoot, ".reweave-capture-job-v1"), "utf8");
  } catch {
    throw new Rejection("execution_bundle_failed");
  }
  if (marker !== "reweave-capture-private-job.v1\n") {
    throw new Rejection("execution_bundle_failed");
  }
  const temporaryRoot = await fs.mkdtemp(path.join(requestedRoot, "bundle-"));
  await fs.chmod(temporaryRoot, 0o700);
  let built;
  try {
    built = await build({
      entryPoints: [computationAdapterEntry],
      absWorkingDir: temporaryRoot,
      ...options,
      plugins: [plugin],
    });
  } catch {
    throw new Rejection("execution_bundle_failed");
  } finally {
    await fs.rm(temporaryRoot, { recursive: true, force: true });
  }
  if (built.warnings.length !== 0 || built.outputFiles.length !== 1) {
    throw new Rejection("execution_bundle_failed");
  }
  const output = built.outputFiles[0].contents;
  if (output.length > 1024 * 1024) throw new Rejection("execution_bundle_too_large");
  const outputMeta = Object.values(built.metafile?.outputs || {});
  if (outputMeta.length !== 1 || outputMeta[0].imports.length !== 0) {
    throw new Rejection("execution_bundle_failed");
  }
  const inputPaths = Object.keys(built.metafile?.inputs || {}).map((value) => value.replace(/^reweave-snapshot:/u, ""));
  if (inputPaths.length !== 2 || !inputPaths.includes(computationCaptureEntry)
      || !inputPaths.includes(computationAdapterEntry)) {
    throw new Rejection("execution_bundle_failed");
  }
  const source = Buffer.from(output).toString("utf8");
  const tree = parseModule("execution-bundle.js", source);
  hasForbiddenBundleNode(tree);
  const optionsBytes = Buffer.from(JSON.stringify(canonicalValue(options)), "utf8");
  return {
    schema_version: "reweave_execution_bundle.v1",
    status: "passed",
    source_base64: Buffer.from(output).toString("base64"),
    sha256: sha256(output),
    size_bytes: output.length,
    esbuild_version: esbuildVersion,
    bundle_options_sha256: sha256(optionsBytes),
  };
}

try {
  if (input.mode === "bundle") {
    const tree = parseModule("bundle.js", String(input.source || ""));
    hasForbiddenBundleNode(tree);
    process.stdout.write(JSON.stringify({ schema_version: "javascript_bundle_security.v1", status: "passed" }));
  } else if (input.mode === "execution_bundle_v2") {
    process.stdout.write(JSON.stringify(await buildExecutionBundleV2()));
  } else {
    process.stdout.write(JSON.stringify(analyzeCandidate()));
  }
} catch (error) {
  const code = error instanceof Rejection ? error.code : "javascript_security_analyzer_failed";
  process.stdout.write(JSON.stringify({ schema_version: "javascript_security.v1", status: "rejected", error_code: code }));
}
