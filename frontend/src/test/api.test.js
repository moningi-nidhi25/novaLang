import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, compile, getExample, listExamples } from '../api'

const reply = (body, status = 200) => ({ ok: status < 400, status, json: async () => body })

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('posts the source as JSON to the chosen endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    await compile('print(1);', 'analyze')
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/analyze')
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body)).toEqual({ source: 'print(1);' })
  })

  it('defaults to the full compile endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply({}))
    vi.stubGlobal('fetch', fetchMock)
    await compile('')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/compile')
  })

  it('explains an unreachable server', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('failed')))
    await expect(compile('x')).rejects.toThrow(/uvicorn backend\.main:app/)
    await expect(compile('x')).rejects.toBeInstanceOf(ApiError)
  })

  it('explains a 422 and other HTTP errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({}, 422)))
    await expect(compile('x')).rejects.toThrow(/100,000/)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({}, 500)))
    await expect(compile('x')).rejects.toThrow(/HTTP 500/)
  })

  it('lists and loads examples (names are URL-encoded)', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(reply({ examples: ['a', 'b'] }))
      .mockResolvedValueOnce(reply({ name: 'a b', source: 's' }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await listExamples()).toEqual(['a', 'b'])
    await getExample('a b')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/examples/a%20b')
  })
})
