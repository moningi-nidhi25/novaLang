// Thin client for the FastAPI backend. All compiler work happens on the server.

const BASE = import.meta.env?.VITE_API_URL ?? ''

export class ApiError extends Error {}

async function request(path, options) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, options)
  } catch {
    throw new ApiError(
      'Cannot reach the NovaLang server. Start it with: uvicorn backend.main:app --port 8000',
    )
  }
  if (!response.ok) {
    throw new ApiError(
      response.status === 422
        ? 'The server rejected the request (is the program longer than 100,000 characters?).'
        : `The server answered with an error (HTTP ${response.status}).`,
    )
  }
  return response.json()
}

/** endpoint: "compile" (all stages) or "analyze" (through the symbol table) etc. */
export function compile(source, endpoint = 'compile') {
  return request(`/api/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source }),
  })
}

export const listExamples = () => request('/api/examples').then((d) => d.examples)
export const getExample = (name) => request(`/api/examples/${encodeURIComponent(name)}`)
