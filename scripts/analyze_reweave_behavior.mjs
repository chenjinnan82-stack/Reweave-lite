import process from "node:process";
import * as ts from "typescript";

const input = JSON.parse(await new Promise((resolve) => {
  let data = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => { data += chunk; });
  process.stdin.on("end", () => resolve(data));
}));
const source = String(input.source || "");
const filename = String(input.filename || "source.js");
const tree = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);

const domBindings = new Map();
const namedFunctions = new Map();
const pureFunctions = new Map();
const allowedGlobals = new Set(["Boolean", "JSON", "Math", "Number", "String", "parseFloat", "parseInt"]);
const allowedCallableGlobals = new Set(["Boolean", "Number", "String", "parseFloat", "parseInt"]);
const allowedArrayMethods = new Set(["reduce"]);
const allowedMathMethods = new Set(["abs", "ceil", "floor", "max", "min", "round", "trunc"]);

function stringValue(node) {
  return node && ts.isStringLiteralLike(node) ? node.text : "";
}

function domTarget(node) {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return "";
  const owner = node.expression.expression;
  const method = node.expression.name.text;
  if (!ts.isIdentifier(owner) || owner.text !== "document" || !["getElementById", "querySelector"].includes(method)) return "";
  const value = stringValue(node.arguments[0]);
  return method === "querySelector" && value.startsWith("#") ? value.slice(1) : value;
}

for (const statement of tree.statements) {
  if (!ts.isVariableStatement(statement)) continue;
  for (const declaration of statement.declarationList.declarations) {
    if (ts.isIdentifier(declaration.name) && declaration.initializer) {
      const target = domTarget(declaration.initializer);
      if (target) domBindings.set(declaration.name.text, target);
    }
  }
}

function isReferenceIdentifier(node) {
  const parent = node.parent;
  if (!parent) return true;
  if ((ts.isFunctionDeclaration(parent) || ts.isParameter(parent) || ts.isVariableDeclaration(parent)) && parent.name === node) return false;
  if (ts.isPropertyAccessExpression(parent) && parent.name === node) return false;
  if (ts.isPropertyAssignment(parent) && parent.name === node && !parent.questionToken) return false;
  return true;
}

for (const statement of tree.statements) {
  if (ts.isFunctionDeclaration(statement) && statement.name && statement.body) {
    namedFunctions.set(statement.name.text, statement);
  }
}

function analyzeFunction(node) {
  if (!node.name || !node.body || node.asteriskToken || node.modifiers?.some((item) => item.kind === ts.SyntaxKind.AsyncKeyword)) return null;
  const params = node.parameters.map((item) => ts.isIdentifier(item.name) && !item.initializer && !item.dotDotDotToken ? item.name.text : "");
  if (!params.length || params.some((item) => !item)) return null;
  const declared = new Set([node.name.text, ...params]);
  const dependencies = new Set();
  let hasReturn = false;
  let valid = true;
  function visit(current) {
    if (!valid) return;
    if (current !== node && ts.isFunctionLike(current)) { valid = false; return; }
    if (ts.isVariableDeclaration(current) && ts.isIdentifier(current.name)) declared.add(current.name.text);
    if (ts.isReturnStatement(current) && current.expression) hasReturn = true;
    if (ts.isNewExpression(current) || ts.isAwaitExpression(current)) { valid = false; return; }
    ts.forEachChild(current, visit);
  }
  visit(node.body);
  if (!valid || !hasReturn) return null;
  function checkIdentifiers(current) {
    if (!valid) return;
    if (ts.isIdentifier(current) && isReferenceIdentifier(current)) {
      const name = current.text;
      if (!declared.has(name) && !allowedGlobals.has(name)) {
        if (namedFunctions.has(name)) dependencies.add(name);
        else valid = false;
      }
    }
    ts.forEachChild(current, checkIdentifiers);
  }
  checkIdentifiers(node.body);
  return valid ? { params, dependencies: [...dependencies] } : null;
}

function pureClosure(name, stack = new Set()) {
  if (stack.has(name)) return null;
  const node = namedFunctions.get(name);
  const analysis = node ? analyzeFunction(node) : null;
  if (!node || !analysis) return null;
  const next = new Set(stack).add(name);
  const ordered = [];
  for (const dependency of analysis.dependencies) {
    const closure = pureClosure(dependency, next);
    if (!closure) return null;
    for (const item of closure) if (!ordered.includes(item)) ordered.push(item);
  }
  ordered.push(name);
  return ordered;
}

for (const [name, statement] of namedFunctions) {
  const closure = pureClosure(name);
  if (!closure) continue;
  pureFunctions.set(name, {
    name,
    params: statement.parameters.map((item) => item.name.text),
    source: closure.map((item) => namedFunctions.get(item).getText(tree)).join("\n"),
  });
}

function pureCallback(node, scope) {
  if ((!ts.isArrowFunction(node) && !ts.isFunctionExpression(node)) || node.asteriskToken || node.modifiers?.some((item) => item.kind === ts.SyntaxKind.AsyncKeyword)) return false;
  const params = node.parameters.map((item) => ts.isIdentifier(item.name) && !item.initializer && !item.dotDotDotToken ? item.name.text : "");
  if (params.some((item) => !item)) return false;
  const next = new Set([...scope, ...params]);
  if (!ts.isBlock(node.body)) return pureStateExpression(node.body, next);
  if (node.body.statements.length !== 1 || !ts.isReturnStatement(node.body.statements[0]) || !node.body.statements[0].expression) return false;
  return pureStateExpression(node.body.statements[0].expression, next);
}

function pureStateExpression(node, scope) {
  if (
    ts.isNumericLiteral(node)
    || ts.isStringLiteralLike(node)
    || node.kind === ts.SyntaxKind.TrueKeyword
    || node.kind === ts.SyntaxKind.FalseKeyword
    || node.kind === ts.SyntaxKind.NullKeyword
  ) return true;
  if (ts.isIdentifier(node)) return scope.has(node.text) || allowedGlobals.has(node.text);
  if (ts.isParenthesizedExpression(node)) return pureStateExpression(node.expression, scope);
  if (ts.isPropertyAccessExpression(node)) return node.expression.kind !== ts.SyntaxKind.ThisKeyword && pureStateExpression(node.expression, scope);
  if (ts.isElementAccessExpression(node)) return pureStateExpression(node.expression, scope) && !!node.argumentExpression && pureStateExpression(node.argumentExpression, scope);
  if (ts.isPrefixUnaryExpression(node)) {
    return [ts.SyntaxKind.ExclamationToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.PlusToken, ts.SyntaxKind.TildeToken].includes(node.operator)
      && pureStateExpression(node.operand, scope);
  }
  if (ts.isBinaryExpression(node)) {
    const operators = new Set([
      ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken,
      ts.SyntaxKind.SlashToken, ts.SyntaxKind.PercentToken, ts.SyntaxKind.AsteriskAsteriskToken,
      ts.SyntaxKind.LessThanToken, ts.SyntaxKind.LessThanEqualsToken,
      ts.SyntaxKind.GreaterThanToken, ts.SyntaxKind.GreaterThanEqualsToken,
      ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.EqualsEqualsEqualsToken,
      ts.SyntaxKind.ExclamationEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken,
      ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken,
      ts.SyntaxKind.QuestionQuestionToken,
    ]);
    return operators.has(node.operatorToken.kind)
      && pureStateExpression(node.left, scope)
      && pureStateExpression(node.right, scope);
  }
  if (ts.isConditionalExpression(node)) {
    return pureStateExpression(node.condition, scope)
      && pureStateExpression(node.whenTrue, scope)
      && pureStateExpression(node.whenFalse, scope);
  }
  if (ts.isArrayLiteralExpression(node)) return node.elements.every((item) => pureStateExpression(item, scope));
  if (ts.isCallExpression(node)) {
    if (ts.isIdentifier(node.expression)) {
      return allowedCallableGlobals.has(node.expression.text) && node.arguments.every((item) => pureStateExpression(item, scope));
    }
    if (!ts.isPropertyAccessExpression(node.expression)) return false;
    const owner = node.expression.expression;
    const method = node.expression.name.text;
    if (ts.isIdentifier(owner) && owner.text === "Math") {
      return allowedMathMethods.has(method) && node.arguments.every((item) => pureStateExpression(item, scope));
    }
    if (!allowedArrayMethods.has(method) || !pureStateExpression(owner, scope)) return false;
    return node.arguments.every((item) => (
      ts.isArrowFunction(item) || ts.isFunctionExpression(item)
        ? pureCallback(item, scope)
        : pureStateExpression(item, scope)
    ));
  }
  return false;
}

const stateBehaviors = [];
for (const statement of tree.statements) {
  if (!ts.isClassDeclaration(statement) || !statement.name) continue;
  for (const member of statement.members) {
    if (!ts.isMethodDeclaration(member) || !member.body || !member.name || !ts.isIdentifier(member.name)) continue;
    if (member.asteriskToken || member.modifiers?.some((item) => item.kind === ts.SyntaxKind.AsyncKeyword)) continue;
    const params = member.parameters.map((item) => ts.isIdentifier(item.name) && !item.initializer && !item.dotDotDotToken ? item.name.text : "");
    if (!params.length || params.some((item) => !item) || member.body.statements.length !== 1) continue;
    const body = member.body.statements[0];
    if (!ts.isExpressionStatement(body) || !ts.isBinaryExpression(body.expression)) continue;
    const assignment = body.expression;
    if (assignment.operatorToken.kind !== ts.SyntaxKind.EqualsToken || !ts.isPropertyAccessExpression(assignment.left)) continue;
    if (assignment.left.expression.kind !== ts.SyntaxKind.ThisKeyword || !pureStateExpression(assignment.right, new Set(params))) continue;
    const methodName = member.name.text;
    stateBehaviors.push({
      class_name: statement.name.text,
      method_name: methodName,
      params,
      state_property: assignment.left.name.text,
      source: `function ${methodName}(${params.join(", ")}) { return ${assignment.right.getText(tree)}; }`,
      evidence: member.getText(tree),
    });
  }
}

function inputBinding(node, locals = new Map()) {
  let current = node;
  if (ts.isCallExpression(current) && ts.isIdentifier(current.expression) && ["Number", "parseFloat", "parseInt", "String"].includes(current.expression.text)) {
    current = current.arguments[0];
  }
  if (ts.isIdentifier(current)) return locals.get(current.text) || "";
  if (!ts.isPropertyAccessExpression(current) || current.name.text !== "value" || !ts.isIdentifier(current.expression)) return "";
  return domBindings.get(current.expression.text) || "";
}

function eventTarget(node) {
  if (!ts.isPropertyAccessExpression(node) || node.name.text !== "addEventListener") return "";
  return ts.isIdentifier(node.expression) ? domBindings.get(node.expression.text) || "" : domTarget(node.expression);
}

const behaviors = [];
function inspectEvent(call) {
  if (!ts.isCallExpression(call)) return;
  const actionId = eventTarget(call.expression);
  const event = stringValue(call.arguments[0]);
  const rawHandler = call.arguments[1];
  if (!rawHandler) return;
  const handler = ts.isIdentifier(rawHandler) ? namedFunctions.get(rawHandler.text) : rawHandler;
  if (!actionId || event !== "click" || !handler || !ts.isFunctionLike(handler) || !handler.body || !ts.isBlock(handler.body)) return;
  const locals = new Map();
  const executable = [];
  for (const statement of handler.body.statements) {
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || !declaration.initializer) return;
        const inputId = inputBinding(declaration.initializer);
        if (!inputId) return;
        locals.set(declaration.name.text, inputId);
      }
    } else {
      executable.push(statement);
    }
  }
  if (executable.length !== 1) return;
  const statement = executable[0];
  if (!ts.isExpressionStatement(statement) || !ts.isBinaryExpression(statement.expression)) return;
  const assignment = statement.expression;
  if (assignment.operatorToken.kind !== ts.SyntaxKind.EqualsToken || !ts.isPropertyAccessExpression(assignment.left)) return;
  if (!ts.isIdentifier(assignment.left.expression) || !["textContent", "innerText", "value"].includes(assignment.left.name.text)) return;
  const outputId = domBindings.get(assignment.left.expression.text) || "";
  const invocation = assignment.right;
  if (!outputId || !ts.isCallExpression(invocation) || !ts.isIdentifier(invocation.expression)) return;
  const logic = pureFunctions.get(invocation.expression.text);
  if (!logic || invocation.arguments.length !== logic.params.length) return;
  const inputIds = invocation.arguments.map((item) => inputBinding(item, locals));
  if (inputIds.some((item) => !item)) return;
  behaviors.push({
    action: { id: actionId, event },
    inputs: logic.params.map((name, index) => ({ id: inputIds[index], parameter: name })),
    output: { id: outputId, property: assignment.left.name.text },
    logic,
  });
}

function walk(node) {
  if (ts.isCallExpression(node)) inspectEvent(node);
  ts.forEachChild(node, walk);
}
walk(tree);

process.stdout.write(JSON.stringify({
  schema_version: 1,
  status: behaviors.length || stateBehaviors.length ? "closed" : "blocked",
  behaviors,
  state_behaviors: stateBehaviors,
}));
