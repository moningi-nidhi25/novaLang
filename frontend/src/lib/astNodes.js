// Helpers for reading the AST JSON the backend sends (shared by the list and diagram views).

const META = new Set(['type', 'label', 'line', 'column', 'inferred_type'])

export const isNode = (v) =>
  v !== null && typeof v === 'object' && !Array.isArray(v) && typeof v.type === 'string' && 'line' in v

/** Split a node's fields into plain properties and child nodes (single or list). */
export function splitFields(node) {
  const props = []
  const children = []
  for (const [key, value] of Object.entries(node)) {
    if (META.has(key)) continue
    if (isNode(value)) children.push([key, [value]])
    else if (Array.isArray(value) && value.length && value.every(isNode)) children.push([key, value])
    else if (value !== null && value !== undefined && !(Array.isArray(value) && value.length === 0)) {
      props.push([key, Array.isArray(value) ? value.join(', ') : String(value)])
    }
  }
  return { props, children }
}

/** Child nodes in source order, each with the field name it hangs from ("body[2]", "condition"...). */
export function childList(node) {
  return splitFields(node).children.flatMap(([key, list]) =>
    list.map((child, i) => ({ node: child, field: list.length > 1 ? `${key}[${i}]` : key })))
}
