import fs from "node:fs";
import process from "node:process";
import vm from "node:vm";

const MAX_INPUT_BYTES = 1024 * 1024;
const MAX_CASE_OUTPUT_BYTES = 64 * 1024;
const MAX_OUTPUT_BYTES = 1024 * 1024;
const chunks = [];
let size = 0;
for await (const chunk of process.stdin) {
  size += chunk.length;
  if (size > MAX_INPUT_BYTES) throw new Error("worker_input_too_large");
  chunks.push(chunk);
}

function reject(code) {
  process.stdout.write(JSON.stringify({schema_version: "compute_validation.v1", status: "failed", error_code: code}));
  process.exit(0);
}

try {
  const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const bundle = fs.readFileSync("bundle.js", "utf8");
  const entrypoint = String(request.entrypoint || "");
  const fixtures = Array.isArray(request.fixtures) ? request.fixtures : [];
  if (!["compute", "default"].includes(entrypoint) || !fixtures.length) reject("compute_worker_request_invalid");

  const context = vm.createContext(Object.create(null), {
    codeGeneration: {strings: false, wasm: false},
  });
  new vm.Script(bundle, {filename: "bundle.js"}).runInContext(context, {timeout: 2000});
  const compute = context.ReweaveCandidate?.[entrypoint];
  if (typeof compute !== "function") reject("compute_entrypoint_missing");

  new vm.Script(`
    globalThis.__reweave_deep_freeze = function(value, seen = new Set()) {
      if (value && typeof value === "object" && !seen.has(value)) {
        seen.add(value);
        for (const key of Object.keys(value)) globalThis.__reweave_deep_freeze(value[key], seen);
        Object.freeze(value);
      }
      return value;
    };
    globalThis.__reweave_json_value = function(value, seen = new Set()) {
      if (value === null || typeof value === "string" || typeof value === "boolean") return;
      if (typeof value === "number") { if (!Number.isFinite(value)) throw new Error("non_finite_output"); return; }
      if (typeof value !== "object" || seen.has(value)) throw new Error("non_json_output");
      seen.add(value);
      if (Array.isArray(value)) { for (const item of value) globalThis.__reweave_json_value(item, seen); }
      else { for (const key of Object.keys(value)) globalThis.__reweave_json_value(value[key], seen); }
      seen.delete(value);
    };
  `).runInContext(context, {timeout: 2000});

  const cases = [];
  for (const fixture of fixtures) {
    context.__reweave_fixture_json = JSON.stringify(fixture);
    const encoded = new vm.Script(`
      (() => {
        const firstInput = __reweave_deep_freeze(JSON.parse(__reweave_fixture_json));
        const firstBefore = JSON.stringify(firstInput);
        const first = ReweaveCandidate[${JSON.stringify(entrypoint)}](firstInput);
        if (first && typeof first.then === "function") throw new Error("promise_output_forbidden");
        __reweave_json_value(first);
        if (JSON.stringify(firstInput) !== firstBefore) throw new Error("input_mutated");
        const secondInput = __reweave_deep_freeze(JSON.parse(__reweave_fixture_json));
        const second = ReweaveCandidate[${JSON.stringify(entrypoint)}](secondInput);
        __reweave_json_value(second);
        const firstJson = JSON.stringify(first);
        const secondJson = JSON.stringify(second);
        if (firstJson !== secondJson) throw new Error("compute_not_repeatable");
        return firstJson;
      })()
    `).runInContext(context, {timeout: 2000});
    if (Buffer.byteLength(encoded, "utf8") > MAX_CASE_OUTPUT_BYTES) {
      throw new Error("compute_output_too_large");
    }
    cases.push(JSON.parse(encoded));
  }
  const output = JSON.stringify({schema_version: "compute_validation.v1", status: "passed", cases});
  if (Buffer.byteLength(output, "utf8") > MAX_OUTPUT_BYTES) throw new Error("compute_output_too_large");
  process.stdout.write(output);
} catch (error) {
  const allowed = new Set([
    "compute_not_repeatable", "input_mutated", "non_finite_output", "non_json_output",
    "promise_output_forbidden", "compute_output_too_large", "Script execution timed out after 2000ms",
  ]);
  const message = String(error?.message || "");
  reject(message.startsWith("Script execution timed out") ? "compute_case_timeout" : (allowed.has(message) ? message : "compute_worker_failed"));
}
