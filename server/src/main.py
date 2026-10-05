from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Hello World"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    print(f"Chat message received: {payload.message}", flush=True)
    return ChatResponse(reply="Message received")
