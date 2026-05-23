import asyncio
import logging
from app.agents.orchestrator import run_pipeline

# To ensure logs are printed
logging.basicConfig(level=logging.INFO)

async def test():
    state = await run_pipeline(
        raw_query='Find ISO 9001 certified metal suppliers in Germany',
        query_id='manual-test-001',
        user_id='manual-user',
    )
    print('---')
    print('Status:', state['pipeline_status'])
    print('Candidates found:', len(state.get('candidate_supplier_ids', [])))
    print('Ranked results:', len(state.get('ranked_suppliers', [])))
    if state.get('ranked_suppliers'):
        top = state['ranked_suppliers'][0]
        print(f'Top result: score={top["total_score"]:.2f}')
        print(f'Explanation: {top["explanation"][:100]}...')
    print('Audit entries:', len(state.get('audit_log', [])))
    if state.get('error'):
        print('Error:', state['error'])
    print('---')

asyncio.run(test())
