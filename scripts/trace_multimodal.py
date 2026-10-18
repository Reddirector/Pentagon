import asyncio
import time
from app.db.session import SessionLocal
from app.db.models import Conversation, User
from app.security.keys import resolve_api_key_or_http
from app.services.nvidia_client import make_chat_model
from app.agent.bootstrap import build_registry
from app.agent.loop import TurnRequest, run_turn
from app.agent.schemas import Budget

async def main():
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == 'pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd').first()
        conv = Conversation(user_id=user.id, title='Trace Multi-Modal Test')
        db.add(conv)
        db.commit()
        db.refresh(conv)
        conv_id = conv.id
        key = resolve_api_key_or_http(db, user.id)

    print(f"Created conversation {conv_id}")
    reg = build_registry()
    model = make_chat_model(key, 'meta/llama-3.2-11b-vision-instruct')

    req = TurnRequest(
        user_id=user.id,
        conversation_id=conv_id,
        turn_id='trace-turn-1',
        permission_level=3,
        user_message=(
            "Research the 2026 humanoid robotics landscape (Tesla Optimus Gen 3, Figure 02, Boston Dynamics Atlas). "
            "Deliver a structured executive report with real web photos of the robots, an AI-generated concept image "
            "of future robotic dexterity, a comparison matrix table, and a compiled PDF deliverable."
        ),
        model_id='meta/llama-3.2-11b-vision-instruct',
    )

    t0 = time.time()
    budget = Budget(max_llm_calls=8, max_tool_calls=12, max_seconds=120.0)

    try:
        async for event in run_turn(reg, model, req, budget=budget):
            elapsed = round(time.time() - t0, 1)
            if event.name == "token":
                print(event.payload.get("content", ""), end="", flush=True)
            elif event.name == "tool_start":
                print(f"\n[{elapsed}s] TOOL START: {event.payload}")
            elif event.name == "tool_result":
                summ = str(event.payload.get("summary") or "")[:120]
                print(f"\n[{elapsed}s] TOOL RESULT: {event.payload.get('tool')} ok={event.payload.get('ok')} summary={summ}")
            elif event.name in ("file", "generated_file"):
                print(f"\n[{elapsed}s] DELIVERABLE: {event.payload.get('filename')} (format={event.payload.get('format')})")
            elif event.name == "done":
                print(f"\n[{elapsed}s] DONE: {event.payload}")
            else:
                print(f"\n[{elapsed}s] EVENT: {event.name} -> {str(event.payload)[:100]}")
    except Exception as exc:
        print(f"\n[{round(time.time() - t0, 1)}s] EXCEPTION: {exc}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
