import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react"
import { ArrowUp, Building2, House, MapPin, MessageCircle, Terminal } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

type Message = {
  id: number
  role: "user" | "assistant"
  content: string
}

function App() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<Message[]>([])
  const [isSending, setIsSending] = useState(false)
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

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      })

      if (!response.ok) throw new Error(`HTTP ${response.status}`)

      const data: { reply?: unknown } = await response.json()
      if (typeof data.reply !== "string") throw new Error("Invalid response")
      const reply = data.reply

      setMessages((current) => [
        ...current,
        { id: nextMessageId.current++, role: "assistant", content: reply },
      ])
    } catch {
      setError("Could not reach the API. Check that both services are running, then try again.")
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
            Messages go to FastAPI and appear in the backend container logs. Replies are placeholders for now.
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
                    Send a message to test the local chat connection. The API will log it and send back a confirmation.
                  </p>
                  <div className="mt-8 flex items-center gap-3 text-xs font-medium text-muted-foreground">
                    <span>Write a message</span>
                    <span aria-hidden="true" className="h-px w-5 bg-border" />
                    <span>See it in the API logs</span>
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
                      <span>Waiting for the API…</span>
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
                placeholder="Type a message to test the chat…"
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
