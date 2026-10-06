import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react"
import { ArrowUp, Building2, House, MapPin, MessageCircle, Terminal } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

type Message = {
  id: number
  role: "user" | "assistant"
  content: string
}

type Datasource = "sql" | "vectorstore" | "web_search"
type RouteOutcome = { datasource: Datasource; result?: string }

const ROUTE_MESSAGES: Record<Datasource, string> = {
  sql: "SQL — exact filters, counts, or calculations over listing fields.",
  vectorstore: "Vector search — descriptive search over property listings.",
  web_search: "Web search — recent facts or information outside the listings database.",
}

function isDatasource(value: unknown): value is Datasource {
  return value === "sql" || value === "vectorstore" || value === "web_search"
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
    if (event === "done") {
      if (!isDatasource(values.datasource)) throw new Error("Invalid route from the API.")
      if (values.datasource === "sql" && typeof values.result !== "string") {
        throw new Error("The API ended without a SQL result.")
      }
      selected = {
        datasource: values.datasource,
        result: typeof values.result === "string" ? values.result : undefined,
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
      const reply = outcome.datasource === "sql"
        ? outcome.result!
        : `Selected route: ${ROUTE_MESSAGES[outcome.datasource]}\nSearch and answering will be added in later steps.`

      setMessages((current) => [
        ...current,
        { id: nextMessageId.current++, role: "assistant", content: reply },
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
      <aside className="hidden w-[274px] shrink-0 flex-col border-r border-border bg-[#f0f3ed] px-5 py-6 lg:flex">
        <div className="flex items-center gap-3 px-2">
          <div className="flex size-11 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
            <Building2 aria-hidden="true" size={22} strokeWidth={1.8} />
          </div>
          <div>
            <div className="font-editorial text-[22px] leading-none">Nhà Việt</div>
            <div className="mt-1 text-[11px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
              Property workspace
            </div>
          </div>
        </div>

        <div className="mt-12 px-3 text-[11px] font-semibold tracking-[0.16em] text-muted-foreground uppercase">
          Workspace
        </div>
        <div className="mt-3 flex items-center gap-3 rounded-xl bg-white px-3 py-3 text-sm font-semibold text-primary shadow-[0_1px_3px_rgba(24,55,40,0.08)] ring-1 ring-border/70">
          <MessageCircle aria-hidden="true" size={18} strokeWidth={1.9} />
          Property chat
        </div>

        <div className="mt-auto rounded-2xl bg-white/80 p-4 ring-1 ring-border/70">
          <div className="flex items-center gap-2 text-xs font-semibold text-primary">
            <Terminal aria-hidden="true" size={15} />
            Local prototype
          </div>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            SQL questions return listing results. Vector and web search are route previews for now.
          </p>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[76px] shrink-0 items-center justify-between border-b border-border/70 px-5 sm:px-9">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground lg:hidden">
              <Building2 aria-hidden="true" size={18} />
            </div>
            <div>
              <h1 className="text-[15px] font-semibold tracking-[-0.02em]">Property chat</h1>
              <p className="text-xs text-muted-foreground">Vietnam real estate · local starter</p>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-full bg-[#e9f1e9] px-3 py-1.5 text-[11px] font-semibold text-primary">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-[#39855e]" />
            Local demo
          </div>
        </header>

        <div className="mx-auto flex min-h-0 w-full max-w-[840px] flex-1 flex-col px-5 sm:px-9">
          <section aria-label="Conversation" className="flex min-h-0 flex-1 flex-col">
            <div className="chat-scroll min-h-0 flex-1 overflow-y-auto">
              {messages.length === 0 ? (
                <div className="flex h-full min-h-[300px] flex-col items-center justify-center px-2 pb-6 text-center">
                  <div className="relative mb-8 flex size-[86px] items-center justify-center rounded-[27px] bg-[#e7eee6] text-primary">
                    <House aria-hidden="true" size={37} strokeWidth={1.5} />
                    <span className="absolute -right-2 -bottom-2 flex size-8 items-center justify-center rounded-xl bg-white text-primary shadow-[0_1px_6px_rgba(25,55,39,0.12)]">
                      <MapPin aria-hidden="true" size={16} strokeWidth={2} />
                    </span>
                  </div>
                  <p className="mb-3 text-[11px] font-semibold tracking-[0.2em] text-primary uppercase">
                    Nhà Việt · chat preview
                  </p>
                  <h2 className="font-editorial max-w-[540px] text-[32px] leading-[1.12] sm:text-[42px]">
                    A place to start the conversation.
                  </h2>
                  <p className="mt-5 max-w-[410px] text-sm leading-6 text-muted-foreground">
                    Ask for exact listing filters, counts, or calculations to query the database. Other questions show the selected route.
                  </p>
                  <div className="mt-8 flex items-center gap-3 text-xs font-medium text-muted-foreground">
                    <span>Write a message</span>
                    <span aria-hidden="true" className="h-px w-5 bg-border" />
                    <span>See the selected route</span>
                  </div>
                </div>
              ) : (
                <div className="space-y-6 py-8" role="log" aria-live="polite" aria-relevant="additions text">
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
                        className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-6 whitespace-pre-wrap shadow-sm sm:max-w-[70%] ${
                          message.role === "user"
                            ? "rounded-br-md bg-primary text-primary-foreground"
                            : "rounded-tl-md bg-white text-foreground ring-1 ring-border/70"
                        }`}
                      >
                        {message.content}
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

          <div className="shrink-0 pb-5 pt-3 sm:pb-8">
            {error && (
              <p role="alert" className="mb-3 rounded-xl bg-[#f9eae7] px-4 py-3 text-sm text-[#9b4437]">
                {error}
              </p>
            )}
            <form
              onSubmit={sendMessage}
              className="rounded-[22px] bg-white p-3 shadow-[0_0_0_1px_rgba(34,76,53,0.09),0_5px_24px_rgba(31,55,38,0.06)] focus-within:shadow-[0_0_0_2px_rgba(40,98,67,0.28),0_5px_24px_rgba(31,55,38,0.06)]"
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
                className="min-h-[82px] resize-none border-0 bg-transparent px-2 py-2 text-[14px] shadow-none focus-visible:border-0 focus-visible:ring-0"
              />
              <div className="flex items-end justify-between gap-3 px-1 pb-1">
                <span className="pl-1 text-[11px] text-muted-foreground">
                  Enter to send · Shift + Enter for a new line
                </span>
                <Button type="submit" size="icon" disabled={!input.trim() || isSending} aria-label="Send message">
                  <ArrowUp aria-hidden="true" size={19} strokeWidth={2.2} />
                </Button>
              </div>
            </form>
            <p className="mt-3 text-center text-[11px] text-muted-foreground">
              Local preview · Conversation is not saved
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}

export default App
