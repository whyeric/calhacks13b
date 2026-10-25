const financial =
  /usd|premium|cost|price|swing|payout|effect|revenue|budget|cents/i;
function containsMoney(node) {
  if (!node || typeof node !== "object") return false;
  if (node.type === "Identifier" && financial.test(node.name)) return true;
  return Object.entries(node).some(
    ([key, value]) =>
      key !== "parent" &&
      (Array.isArray(value) ? value.some(containsMoney) : containsMoney(value)),
  );
}
export default {
  meta: {
    type: "problem",
    schema: [],
    messages: {
      math: "Financial values must be formatted directly from API strings; only chartScale.ts may coerce values for pixels.",
    },
  },
  create(context) {
    if (context.filename.replaceAll("\\", "/").endsWith("/lib/chartScale.ts"))
      return {};
    const report = (node) => context.report({ node, messageId: "math" });
    return {
      BinaryExpression(node) {
        if (
          ["+", "-", "*", "/", "%", "**"].includes(node.operator) &&
          containsMoney(node)
        )
          report(node);
      },
      UnaryExpression(node) {
        if (["+", "-"].includes(node.operator) && containsMoney(node))
          report(node);
      },
      UpdateExpression(node) {
        if (containsMoney(node)) report(node);
      },
      AssignmentExpression(node) {
        if (node.operator !== "=" && containsMoney(node)) report(node);
      },
      CallExpression(node) {
        if (
          node.callee.type === "Identifier" &&
          ["Number", "parseFloat", "parseInt"].includes(node.callee.name)
        )
          report(node);
        if (
          node.callee.type === "MemberExpression" &&
          node.callee.object.name === "Math"
        )
          report(node);
      },
      ImportDeclaration(node) {
        if (/decimal|big\.js/i.test(node.source.value)) report(node);
      },
    };
  },
};
