import pytest

from sqlchat.examples import EXAMPLES, select_examples
from sqlchat.llm import GenerationError, OpenAIGenerator, Request, Turn, build_messages, parse_reply
from sqlchat.service import AnalyticsService

from .conftest import TODAY, make_settings
from .helpers import FakeOpenAI, answer

GOOD = "SELECT o.channel, COUNT(*) AS orders FROM sales.orders o WHERE o.status = 'completed' GROUP BY 1"


def make_request(catalog, question="Orders by channel", history=()):
    return Request(question, catalog.to_prompt(), TODAY, catalog.data_start, catalog.data_end,
                   examples=select_examples(question, 2, today=TODAY.isoformat()), history=history)


def llm_service(seeded_db, catalog, fake, **settings):
    s = make_settings(generator="openai", **settings)
    return AnalyticsService(seeded_db, catalog, OpenAIGenerator(s, client=fake.client()), s)


def test_prompt_has_schema_rules_date_examples_and_history(catalog):
    messages = build_messages(make_request(catalog, "and by region?", [Turn("Orders by channel", GOOD)]))
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Today is 2026-09-30" in system and "2024-01-01 to 2026-09-30" in system
    assert "status = 'completed'" in system
    assert "TABLE sales.orders" in user and "email" not in user
    assert "Examples of correct queries" in user and GOOD in user
    assert user.rstrip().endswith("Question: and by region?")


@pytest.mark.parametrize("text,sql", [
    ('{"sql": "SELECT 1", "explanation": "x", "chart": null}', "SELECT 1"),
    ('Sure!\n```json\n{"sql": "SELECT 2", "explanation": "x"}\n```', "SELECT 2"),
    ('{"sql": "```sql\\nSELECT 3\\n```", "explanation": "x"}', "SELECT 3"),
    ('{"sql": null, "explanation": "no data about stock"}', None),
    ('{"sql": "  ", "explanation": "x"}', None),
])
def test_parse_reply(text, sql):
    assert parse_reply(text).sql == sql


@pytest.mark.parametrize("text", ["no json here", "{not json}", "[1, 2]", '{"sql": 5}'])
def test_parse_reply_rejects_garbage(text):
    with pytest.raises(GenerationError):
        parse_reply(text)


def test_generate_sends_strict_schema_and_returns_draft(catalog):
    fake = FakeOpenAI().reply(answer(GOOD, "Orders per channel."))
    gen = OpenAIGenerator(make_settings(), client=fake.client())
    draft = gen.generate(make_request(catalog))
    assert draft.sql == GOOD and draft.explanation == "Orders per channel."
    req = fake.requests[0]
    assert req["temperature"] == 0
    assert req["response_format"]["type"] == "json_schema"
    assert req["response_format"]["json_schema"]["strict"] is True


def test_json_object_mode_for_ollama(catalog):
    fake = FakeOpenAI().reply(answer(GOOD))
    gen = OpenAIGenerator(make_settings(llm_json_mode="json_object"), client=fake.client())
    gen.generate(make_request(catalog))
    assert fake.requests[0]["response_format"] == {"type": "json_object"}


def test_http_errors_and_truncation_become_generation_errors(catalog):
    fake = FakeOpenAI().fail(503).reply("{", finish_reason="length")
    gen = OpenAIGenerator(make_settings(), client=fake.client())
    with pytest.raises(GenerationError, match="HTTP 503"):
        gen.generate(make_request(catalog))
    with pytest.raises(GenerationError, match="cut off"):
        gen.generate(make_request(catalog))


def test_repair_loop_sends_the_postgres_error_back(seeded_db, catalog):
    fake = FakeOpenAI()
    fake.reply(answer("SELECT channel, SUM(revenue) FROM sales.orders GROUP BY 1"))
    fake.reply(answer(GOOD, "Orders per channel.", {"type": "bar", "x": "channel", "y": ["orders"], "series": None}))
    result = llm_service(seeded_db, catalog, fake).ask("Orders by channel")
    assert result.status == "ok" and result.sql == GOOD
    assert len(result.failed_attempts) == 1
    assert result.failed_attempts[0].stage == "database"
    assert 'column "revenue" does not exist' in result.failed_attempts[0].error
    # the fix request continues the same conversation
    second = fake.requests[1]["messages"]
    assert second[-2]["role"] == "assistant" and "SUM(revenue)" in second[-2]["content"]
    assert 'column "revenue" does not exist' in second[-1]["content"]
    assert result.chart["type"] == "bar"


def test_repair_loop_fixes_validator_refusals(seeded_db, catalog):
    fake = FakeOpenAI()
    fake.reply(answer("SELECT * FROM sales.customers"))
    fake.reply(answer("SELECT segment, COUNT(*) AS customers FROM sales.customers GROUP BY 1"))
    result = llm_service(seeded_db, catalog, fake).ask("Customers by segment")
    assert result.status == "ok"
    assert result.failed_attempts[0].stage == "validation"
    assert "restricted" in fake.requests[1]["messages"][-1]["content"]


def test_repair_gives_up_after_max_repairs(seeded_db, catalog):
    fake = FakeOpenAI()
    for _ in range(3):
        fake.reply(answer("SELECT nope FROM sales.orders"))
    result = llm_service(seeded_db, catalog, fake, max_repairs=2).ask("Orders by channel")
    assert result.status == "error" and len(result.failed_attempts) == 3
    assert len(fake.requests) == 3
    assert "nope" in result.error


def test_unanswerable_reply(seeded_db, catalog):
    fake = FakeOpenAI().reply(answer(None, "There is no inventory data."))
    result = llm_service(seeded_db, catalog, fake).ask("What's in stock?")
    assert result.status == "unanswerable" and result.explanation == "There is no inventory data."
    assert result.result is None


def test_model_outage_is_reported_not_raised(seeded_db, catalog):
    fake = FakeOpenAI().fail(500)
    result = llm_service(seeded_db, catalog, fake).ask("Orders by channel")
    assert result.status == "error" and "HTTP 500" in result.error


def test_select_examples_prefers_overlapping_words():
    picked = select_examples("How many new customers signed up per month?", 2, today="2026-09-30")
    assert "new customers" in picked[0].question
    week = [e for e in select_examples("weekly revenue last 8 weeks", 1, today="2026-09-30")][0]
    assert "DATE '2026-09-30'" in week.sql and "{today}" not in week.sql
    assert select_examples("anything", 0, today="x") == []


def test_every_few_shot_example_passes_the_guard_and_runs(service):
    for ex in EXAMPLES:
        result = service.execute(ex.sql.replace("{today}", TODAY.isoformat()))
        assert result.row_count > 0 or "never" in ex.question, ex.question

def trace_request(data=None):
    if data is None:
        return None
    return data