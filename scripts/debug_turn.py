import asyncio
import time
from app.db.session import SessionLocal
from app.security.keys import resolve_api_key_or_http
from app.services.nvidia_client import make_chat_model
from app.agent.bootstrap import build_registry
from app.agent.loop import TurnRequest, run_turn
from app.agent.schemas import Budget

async def test():
    with SessionLocal() as db:
        key = resolve_api_key_or_http(db, "pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd")
    reg = build_registry()
    model = make_chat_model(key, "meta/llama-3.2-11b-vision-instruct")
    
    req = TurnRequest(
        user_id="pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd",
        conversation_id="debug-run-1",
        turn_id="turn-debug-1",
        permission_level=3,
        user_message="Research the 2026 humanoid robotics landscape (Tesla Optimus Gen 3, Figure 02, Boston Dynamics Atlas). Deliver a structured executive report with real web photos of the robots, an AI-generated concept image of future robotic dexterity, a comparison matrix table, and a compiled PDF deliverable.",
        model_id="meta/llama-3.2-11b-vision-instruct",
    )
    t0 = time.time()
    print("=== Starting direct run_turn execution ===")
    async for event in run_turn(reg, model, req, budget=Budget(max_llm_calls=8, max_tool_calls=10, max_seconds=180.0)):
        elapsed = round(time.time() - t0, 1)
        if event.name == "token":
            print(event.payload.get("content", ""), end="", flush=True)
        elif event.name == "tool_start":
            print(f"\n[{elapsed}s] TOOL START: {event.payload}")
        elif event.name == "tool_result":
            t_name = event.payload.get("tool")
            ok = event.payload.get("ok")
            summ = str(event.payload.get("summary") or "")[:80]
            print(f"\n[{elapsed}s] TOOL RESULT: {t_name} ok={ok} summary={summ}")
        elif event.name in ("file", "generated_file"):
            print(f"\n[{elapsed}s] DELIVERABLE: {event.payload.get('filename')}")
        elif event.name == "done":
            print(f"\n[{elapsed}s] DONE: {event.payload}")
        else:
            print(f"\n[{elapsed}s] EVENT: {event.name}")

if __name__ == "__main__":
    asyncio.run(test())
