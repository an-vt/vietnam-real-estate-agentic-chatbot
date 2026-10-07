import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react"
import { ArrowUp, Database, ExternalLink, House, MapPin } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

type Message = {
  id: number
  role: "user" | "assistant"
  content: string
  sources?: Source[]
}

type Datasource = "sql" | "vectorstore" | "web_search"
type Source = { title: string; url: string }
type RouteOutcome = { datasource: Datasource; result: string; sources: Source[] }

function isDatasource(value: unknown): value is Datasource {
  return value === "sql" || value === "vectorstore" || value === "web_search"
}

function isSource(value: unknown): value is Source {
  if (typeof value !== "object" || value === null) return false
  const source = value as Record<string, unknown>
  return typeof source.title === "string" && typeof source.url === "string"
}

async function readRouteStream(response: Response, onStep: (label: string) => void): Promise<RouteOutcome> {
  if (!response.ok || !response.body) throw new Error(`Routing request failed (HTTP ${response.status}).`)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let selected: RouteOutcome | null = null

  function handleEvent(raw: string) {
    const lines = raw.split("\n")
    const event = lines.find((line) => line.startsWith("event: "))?.slice(7)
    const dataText = lines.filter((line) => line.startsWith("data: ")).map((line) => line.slice(6)).join("\n")
    if (!event || !dataText) return

    const data: unknown = JSON.parse(dataText)
    if (typeof data !== "object" || data === null) throw new Error("Invalid routing event.")
    const values = data as Record<string, unknown>

    if (event === "error") {
      throw new Error(typeof values.message === "string" ? values.message : "Routing failed.")
    }
    if (event === "step" && values.node === "route") {
      if (values.status === "running") onStep("Routing the question…")
      if (values.status === "completed" && isDatasource(values.datasource)) {
        onStep(`Selected ${values.datasource}`)
      }
    }
    if (event === "step" && values.node === "query_sql") {
      if (values.status === "running") onStep("Querying listings…")
      if (values.status === "completed") onStep("SQL query completed")
    }
    if (event === "step" && values.node === "retrieve") {
      if (values.status === "running") onStep("Searching listings…")
      if (values.status === "completed") onStep("Listings retrieved")
    }
    if (event === "step" && values.node === "grade_documents") {
      if (values.status === "running") onStep("Checking listing relevance…")
      if (values.status === "completed") onStep("Listing check completed")
    }
    if (event === "step" && values.node === "rewrite_query") {
      if (values.status === "running") onStep("Improving search query…")
      if (values.status === "completed") onStep("Searching again…")
    }
    if (event === "step" && values.node === "web_search") {
      if (values.status === "running") onStep("Searching the web…")
      if (values.status === "completed") onStep("Web sources checked")
    }
    if (event === "step" && values.node === "generate") {
      if (values.status === "running") onStep("Preparing the answer…")
    }
    if (event === "done") {
      if (!isDatasource(values.datasource)) throw new Error("Invalid route from the API.")
      if (typeof values.result !== "string") {
        throw new Error("The API ended without a result.")
      }
      const sources = values.datasource === "web_search" && Array.isArray(values.sources)
        ? values.sources.filter(isSource) : []
      selected = {
        datasource: values.datasource,
        result: values.result,
        sources,
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n")
    let boundary = buffer.indexOf("\n\n")
    while (boundary !== -1) {
      handleEvent(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf("\n\n")
    }
  }
  buffer += decoder.decode()
  if (buffer.trim()) handleEvent(buffer.trim())
  if (!selected) throw new Error("The API ended without a route.")
  return selected
}

function App() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<Message[]>([])
  const [isSending, setIsSending] = useState(false)
  const [agentStep, setAgentStep] = useState("Routing the question…")
  const [error, setError] = useState<string | null>(null)
  const nextMessageId = useRef(0)
  const messagesEnd = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ block: "end" })
  }, [messages, isSending])

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const message = input.trim()

    if (!message || isSending) return

    setMessages((current) => [
      ...current,
      { id: nextMessageId.current++, role: "user", content: message },
    ])
    setInput("")
    setError(null)
    setIsSending(true)
    setAgentStep("Routing the question…")

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      })

      const outcome = await readRouteStream(response, setAgentStep)

      setMessages((current) => [
        ...current,
        { id: nextMessageId.current++, role: "assistant", content: outcome.result, sources: outcome.sources },
      ])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not complete routing. Please try again.")
    } finally {
      setIsSending(false)
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <div className="flex h-dvh min-h-[480px] bg-background text-foreground">
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-border/70 bg-background/95 px-4 backdrop-blur sm:px-6 md:px-8 lg:px-10">
          <div className="mx-auto flex h-[68px] max-w-[1120px] items-center justify-between gap-3 sm:h-[76px] sm:gap-6">
            <div>
              <h1 className="font-editorial text-[22px] leading-none sm:text-[24px] md:text-[27px]">Nhà Việt</h1>
              <p className="mt-1.5 hidden text-[11px] font-medium tracking-[0.12em] text-muted-foreground uppercase sm:block">
                Vietnam real estate chat
              </p>
            </div>
            <a
              href="https://www.kaggle.com/datasets/qmanhbeo/vietnamese-real-estate-listings-may-2024/data"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Open Vietnamese Real Estate Listings May 2024 dataset on Kaggle"
              className="group flex min-w-0 max-w-[145px] items-center gap-1.5 rounded-full px-1.5 py-2 text-right text-[10px] leading-4 text-muted-foreground transition-[background-color,color] duration-150 hover:bg-muted hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:max-w-[270px] sm:gap-2 sm:px-2 sm:text-xs"
            >
              <Database aria-hidden="true" className="hidden shrink-0 text-primary sm:block" size={16} strokeWidth={1.8} />
              <span className="truncate sm:hidden">May 2024 dataset</span>
              <span className="hidden truncate sm:inline">Vietnamese Real Estate Listings · May 2024</span>
              <ExternalLink aria-hidden="true" className="shrink-0 text-primary" size={13} strokeWidth={1.8} />
            </a>
          </div>
        </header>

        <div className="mx-auto flex min-h-0 w-full max-w-[900px] flex-1 flex-col px-4 sm:px-6 md:max-w-[820px] md:px-8 lg:max-w-[900px] lg:px-10 xl:max-w-[980px]">
          <section aria-label="Conversation" className="flex min-h-0 flex-1 flex-col">
            <div className="chat-scroll min-h-0 flex-1 overflow-y-auto">
              {messages.length === 0 ? (
                <div className="flex h-full min-h-[280px] flex-col items-center justify-center px-2 pb-5 text-center sm:min-h-[320px] md:min-h-[380px] lg:min-h-[420px]">
                  <div className="relative mb-6 flex size-[64px] items-center justify-center rounded-[22px] bg-[#e7eee6] text-primary sm:mb-7 sm:size-[72px] sm:rounded-[24px]">
                    <House aria-hidden="true" size={28} strokeWidth={1.5} className="sm:hidden" />
                    <House aria-hidden="true" size={31} strokeWidth={1.5} className="hidden sm:block" />
                    <span className="absolute -right-2 -bottom-2 flex size-7 items-center justify-center rounded-xl bg-white text-primary shadow-[0_1px_6px_rgba(25,55,39,0.12)]">
                      <MapPin aria-hidden="true" size={14} strokeWidth={2} />
                    </span>
                  </div>
                  <p className="mb-3 text-[10px] font-semibold tracking-[0.16em] text-primary uppercase sm:text-[11px] sm:tracking-[0.2em]">
                    Nhà Việt · property assistant
                  </p>
                  <h2 className="font-editorial max-w-[560px] text-[30px] leading-[1.08] sm:text-[36px] md:text-[42px] lg:text-[44px]">
                    Find your next place in Vietnam.
                  </h2>
                  <p className="mt-4 max-w-[330px] text-[13px] leading-5 text-muted-foreground sm:mt-5 sm:max-w-[420px] sm:text-sm sm:leading-6">
                    Ask about prices, locations, property details, or recent real-estate facts.
                  </p>
                </div>
              ) : (
                <div className="space-y-4 py-5 sm:space-y-6 sm:py-8" role="log" aria-live="polite" aria-relevant="additions text">
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className={`flex gap-3 ${message.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                      {message.role === "assistant" && (
                        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-[#e7eee6] text-primary">
                          <House aria-hidden="true" size={18} strokeWidth={1.8} />
                        </div>
                      )}
                      <div
                        className={`max-w-[88%] rounded-2xl px-3.5 py-3 text-sm leading-6 whitespace-pre-wrap shadow-sm sm:max-w-[78%] sm:px-4 md:max-w-[70%] ${
                          message.role === "user"
                            ? "rounded-br-md bg-primary text-primary-foreground"
                            : "rounded-tl-md bg-white text-foreground ring-1 ring-border/70"
                        }`}
                      >
                        {message.content}
                        {message.sources && message.sources.length > 0 && (
                          <div className="mt-3 border-t border-border pt-2 text-xs text-muted-foreground">
                            <span className="font-semibold">Sources</span>
                            <div className="mt-1 flex flex-col gap-1">
                              {message.sources.map((source, index) => (
                                <a
                                  key={`${source.url}-${index}`}
                                  href={source.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="break-all text-primary underline underline-offset-2"
                                >
                                  [{index + 1}] {source.title}
                                </a>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  {isSending && (
                    <div className="flex items-center gap-3 text-sm text-muted-foreground" role="status">
                      <div className="flex size-9 items-center justify-center rounded-xl bg-[#e7eee6] text-primary">
                        <House aria-hidden="true" size={18} strokeWidth={1.8} />
                      </div>
                      <span>{agentStep}</span>
                    </div>
                  )}
                  <div ref={messagesEnd} />
                </div>
              )}
            </div>
          </section>

          <div className="shrink-0 pb-4 pt-2 sm:pb-6 sm:pt-3 md:pb-8">
            {error && (
              <p role="alert" className="mb-3 rounded-xl bg-[#f9eae7] px-4 py-3 text-sm text-[#9b4437]">
                {error}
              </p>
            )}
            <form
              onSubmit={sendMessage}
              className="rounded-[18px] bg-white p-2.5 shadow-[0_0_0_1px_rgba(34,76,53,0.09),0_5px_24px_rgba(31,55,38,0.06)] focus-within:shadow-[0_0_0_2px_rgba(40,98,67,0.28),0_5px_24px_rgba(31,55,38,0.06)] sm:rounded-[22px] sm:p-3"
            >
              <label htmlFor="chat-message" className="sr-only">
                Your message
              </label>
              <Textarea
                id="chat-message"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about a property or a recent fact…"
                className="min-h-[72px] resize-none border-0 bg-transparent px-2 py-2 text-[14px] shadow-none focus-visible:border-0 focus-visible:ring-0 sm:min-h-[82px]"
              />
              <div className="flex items-end justify-between gap-2 px-1 pb-1 sm:gap-3">
                <span className="max-w-[190px] pl-1 text-[10px] leading-4 text-muted-foreground sm:max-w-none sm:text-[11px] sm:leading-normal">
                  Enter to send · Shift + Enter for a new line
                </span>
                <Button type="submit" size="icon" disabled={!input.trim() || isSending} aria-label="Send message">
                  <ArrowUp aria-hidden="true" size={19} strokeWidth={2.2} />
                </Button>
              </div>
            </form>
            <p className="mt-3 text-center text-[11px] text-muted-foreground">
              Conversation is not saved
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}

export default App
