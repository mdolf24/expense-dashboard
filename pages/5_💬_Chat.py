import pandas as pd
import streamlit as st
from config import CONFIG, require_access
from data_loader import load_all_months


CLAUDE_MODEL = "claude-haiku-5-5"
MODEL_OPTIONS = {
    "Haiku (cheap)": "claude-haiku-5-5",
    "Sonnet (better analysis)": "claude-sonnet-5-5",
}
MODEL_PRICES_USD_PER_MILLION = {
    "claude-haiku-5-5": {
        "input": 1.00,
        "output": 5.00,
        "cache_write": 1.25,
        "cache_read": 0.10,
    },
    "claude-sonnet-5-5": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
}
MONTHLY_BUDGET = CONFIG.monthly_budgets
DATA_COLUMNS = [
    "Month",
    "Date",
    "Shop",
    "Item",
    "Category",
    "Subcategory",
    "Price",
    "Discount",
    "Final_Price",
    "Who",
    "Split",
    "Exclude_Balance",
]
SYSTEM_PROMPT = """You are a senior personal-finance analyst for a shared household.
The configured household members are {person_one} and {person_two}; explain things clearly.

Answer ONLY what was asked. Do not add extra findings, side observations, suggestions, or
“I also noticed” sections unless explicitly asked.
Default scope is the month and categories mentioned in the question. If no month is mentioned,
use the most recent month in the data. Look at other months only for an explicit comparison,
trend, “compared to before”, or to answer “why higher/lower than usual” (then use at most the
previous month).
Be concise: lead with the direct answer in 1-2 sentences, then at most 3-5 short bullet points
with key figures. Use no headings, long lists, or repeated questions. Maximum about 150 words
by default; go longer only if the user writes “podrobno”, “detailed”, or “razloži v celoti”.
Report only the top 3 drivers (largest items or shops) unless asked for more. Do not restate
dashboard numbers unless they explain the answer. If the question is vague, answer the most
likely interpretation briefly and add one short clarifying question at the end.

Use the analysis tool for every number you report; never add up many rows in your head.
Plan the analysis first and use as few analysis calls as possible, ideally 1-3, combining
several computations in one call. Never explore the full history just in case.
Clearly separate facts from interpretation or guesses, and label guesses as guesses.
Do not mix up who paid and who owes; follow the glossary. Answer in Slovenian or English,
matching the question. Give practical suggestions only when explicitly asked, and never give
investment advice."""
RUN_PYTHON_TOOL = {
    "name": "analyze_expenses",
    "description": (
        "Run a safe, read-only aggregate over the expense DataFrame. "
        "No code is accepted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric": {"type": "string", "enum": ["sum", "mean", "count"]},
            "group_by": {"type": "string", "enum": ["Month", "Category", "Subcategory", "Shop", "Who"]},
            "column": {"type": "string", "enum": ["Final_Price", "Discount", "Price"]},
            "month": {"type": "string"},
        },
        "required": ["metric", "column"],
    },
}
@st.cache_data(ttl=300)
def build_context(dataframe: pd.DataFrame) -> str:
    df = dataframe.reindex(columns=DATA_COLUMNS, fill_value="").copy()
    for column in ("Price", "Discount", "Final_Price"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")

    monthly_total = df.groupby("Month", dropna=False)["Final_Price"].sum()
    category_month = pd.pivot_table(
        df,
        index="Month",
        columns="Category",
        values="Final_Price",
        aggfunc="sum",
        fill_value=0.0,
    )
    aggregates = "\n".join(
        [
            "Convenience aggregates only; the raw CSV below is the source of truth.",
            "Total per month (EUR):",
            monthly_total.to_string(),
            "\nTotal per category per month (EUR):",
            category_month.to_string(),
            "\nMONTHLY_BUDGET (EUR):",
            repr(MONTHLY_BUDGET),
        ]
    )
    glossary = f"""GLOSSARY
- Who is the person who PAID, not whose expense it is.
- Split=yes means shared between {CONFIG.people[0]} and {CONFIG.people[1]}.
- Exclude_Balance=yes means pre-settled (for example rent): it counts as spending but not in who-owes-whom.
- Final_Price = Price - Discount; negative values are refunds/returns.
- Currency is EUR.
- Configured split ratios are {CONFIG.split_ratios[0]:.0%}/{CONFIG.split_ratios[1]:.0%}; pre-settled housing is excluded from balances.
""".format(person_one=CONFIG.people[0], person_two=CONFIG.people[1])
    return (
        f"{glossary}\n{aggregates}\n\nCOMPLETE RAW EXPENSE DATA (CSV; source of truth)\n"
        f"{df.fillna('').to_csv(index=False)}"
    )


def _analyze_expenses(request: dict, dataframe: pd.DataFrame) -> str:
    metric = request.get("metric")
    column = request.get("column")
    group_by = request.get("group_by")
    if metric not in {"sum", "mean", "count"} or column not in {"Final_Price", "Discount", "Price"}:
        return "Error: unsupported metric or column."
    if group_by is not None and group_by not in {"Month", "Category", "Subcategory", "Shop", "Who"}:
        return "Error: unsupported grouping."
    frame = dataframe.copy()
    if request.get("month"):
        frame = frame[frame["Month"].astype(str).eq(str(request["month"]))]
    if group_by:
        values = frame.groupby(group_by)[column]
        result = values.count() if metric == "count" else getattr(values, metric)()
    elif metric == "count":
        result = len(frame)
    else:
        result = getattr(frame[column], metric)()
    return str(result)[:8000]


def _api_error_message(error) -> str:
    if isinstance(error, anthropic.AuthenticationError):
        return "Claude authentication failed: the Anthropic API key is invalid."
    if isinstance(error, anthropic.RateLimitError):
        return "Claude is temporarily rate-limited. Please try again in a moment."
    if isinstance(error, anthropic.APIStatusError) and error.status_code == 402:
        return "Claude API billing or credit is insufficient. Check the Anthropic account billing."
    return f"Claude API error: {error}"


def _text_blocks(response) -> str:
    return "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )


def _validate_messages(messages):
    def block_value(block, key, default=None):
        if isinstance(block, dict):
            return block.get(key, default)
        return getattr(block, key, default)

    for index, message in enumerate(messages):
        if message.get("role") not in {"user", "assistant"}:
            raise ValueError(f"Message {index} has an invalid role.")
        content = message.get("content")
        if content is None or content == "" or content == []:
            raise ValueError(f"Message {index} has empty content.")
        if index and message["role"] == messages[index - 1].get("role"):
            raise ValueError(f"Messages {index - 1} and {index} have the same role.")
        if not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            if block_value(block, "type") != "tool_use":
                continue
            if index + 1 >= len(messages):
                raise ValueError(
                    f"Tool use {block_value(block, 'id')} has no tool result."
                )
            next_content = messages[index + 1].get("content", [])
            expected_ids = [
                block_value(tool_block, "id")
                for tool_block in content
                if block_value(tool_block, "type") == "tool_use"
            ]
            result_ids = [
                block_value(result, "tool_use_id")
                for result in next_content
                if block_value(result, "type") == "tool_result"
            ]
            if result_ids != expected_ids:
                raise ValueError(
                    f"Tool use ids {expected_ids} at block {block_index} "
                    f"are not followed by matching tool results {result_ids}."
                )


def _plain_text_history(messages):
    clean_messages = []
    expected_role = "user"
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") != expected_role
            or not isinstance(message.get("content"), str)
            or not message["content"].strip()
        ):
            break
        clean_messages.append(
            {"role": expected_role, "content": message["content"]}
        )
        expected_role = "assistant" if expected_role == "user" else "user"
    return clean_messages


def _usage_totals(totals, usage):
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        totals[key] += getattr(usage, key, 0) or 0


def _estimated_cost_usd(usage, model):
    prices = MODEL_PRICES_USD_PER_MILLION[model]
    return sum(
        usage[key] * prices[price_key] / 1_000_000
        for key, price_key in (
            ("input_tokens", "input"),
            ("output_tokens", "output"),
            ("cache_creation_input_tokens", "cache_write"),
            ("cache_read_input_tokens", "cache_read"),
        )
    )


st.set_page_config(page_title="Expense Chat", page_icon="💬")
require_access()
st.title("💬 Expense Data Analyst")
st.caption("Ask anything about the complete shared household expense data.")

try:
    api_key = st.secrets.get("anthropic", {}).get("api_key", "").strip()
except Exception:
    api_key = ""
if not api_key:
    st.info("Chat is disabled in demo mode. Add an Anthropic API key in the app secrets to enable it.")
    st.stop()
try:
    import anthropic
except ImportError:
    st.error("The 'anthropic' package is not installed.")
    st.stop()

try:
    expenses = load_all_months()
except Exception as error:
    st.error(f"Could not load expense data from Google Sheets: {error}")
    st.stop()
if expenses.empty:
    st.warning("No non-empty monthly worksheets were found.")
    st.stop()

context = build_context(expenses)
client = anthropic.Anthropic(api_key=api_key)
if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"] = []

with st.sidebar:
    selected_model_label = st.selectbox(
        "Claude model",
        list(MODEL_OPTIONS),
        index=0,
    )
    selected_model = MODEL_OPTIONS[selected_model_label]
    st.button(
        "Clear chat",
        on_click=lambda: st.session_state.update(chat_messages=[]),
        use_container_width=True,
    )
    st.caption("Example questions:")
    st.caption("Why did groceries increase in the last 3 months?")
    st.caption("Kateri mesec je bil najdražji za eating_out?")
    if "last_usage" in st.session_state:
        usage = st.session_state["last_usage"]
        st.caption(
            f"Last response tokens: {usage['input_tokens']:,} in / "
            f"{usage['output_tokens']:,} out\n"
            f"Cache creation: {usage['cache_creation_input_tokens']:,} · "
            f"cache read: {usage['cache_read_input_tokens']:,}"
        )
        st.caption(
            f"Estimated cost ({selected_model_label}): "
            f"${_estimated_cost_usd(usage, usage.get('model', selected_model)):.4f} USD"
        )

st.session_state["chat_messages"] = _plain_text_history(
    st.session_state["chat_messages"]
)
for message in st.session_state["chat_messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about your expenses..."):
    with st.chat_message("user"):
        st.markdown(prompt)

    plain_history = _plain_text_history(st.session_state["chat_messages"])
    api_messages = plain_history + [{"role": "user", "content": prompt}]
    tool_traces = []
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    response_debug = []
    answer_parts = []
    final_answer = ""
    error_message = ""
    refusal_message = ""
    max_token_continuations = 0
    fallback_needed = False
    request_max_tokens = (
        3072
        if any(
            phrase in prompt.lower()
            for phrase in ("podrobno", "detailed", "razloži v celoti")
        )
        else 1024
    )

    with st.chat_message("assistant"):
        def request_answer(messages):
            local_api_messages = list(messages)
            local_answer_parts = []
            local_response_debug = []
            local_tool_traces = []
            local_final_answer = ""
            local_refusal = ""
            local_error = ""
            local_fallback = False
            final_instruction_included = False
            local_max_token_continuations = 0

            for iteration in range(8):
                _validate_messages(local_api_messages)
                response = client.messages.create(
                    model=selected_model,
                    max_tokens=request_max_tokens,
                    system=[
                        {"type": "text", "text": SYSTEM_PROMPT},
                        {
                            "type": "text",
                            "text": context,
                            "cache_control": {"type": "ephemeral"},
                        },
                    ],
                    tools=[RUN_PYTHON_TOOL],
                    messages=local_api_messages,
                )
                _usage_totals(usage_totals, response.usage)
                block_types = [
                    getattr(block, "type", "unknown") for block in response.content
                ]
                local_response_debug.append(
                    {
                        "iteration": iteration + 1,
                        "stop_reason": response.stop_reason,
                        "block_types": block_types,
                        "usage": {
                            key: getattr(response.usage, key, 0) or 0
                            for key in usage_totals
                        },
                    }
                )
                response_text = _text_blocks(response)
                if response_text:
                    local_answer_parts.append(response_text)
                tool_use_blocks = [
                    block
                    for block in response.content
                    if getattr(block, "type", None) == "tool_use"
                ]
                if response.content:
                    local_api_messages.append(
                        {"role": "assistant", "content": response.content}
                    )

                if tool_use_blocks:
                    tool_results = []
                    for block in tool_use_blocks:
                        code = ""
                        try:
                            request = block.input
                            result = _analyze_expenses(request, expenses)
                            is_error = result.startswith("Error")
                        except Exception as error:
                            result = f"Error while running analysis: {error}"
                            is_error = True
                        local_tool_traces.append(
                            {"request": request, "output": result}
                        )
                        tool_result = {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                        if is_error:
                            tool_result["is_error"] = True
                        tool_results.append(tool_result)
                    if iteration == 7:
                        for tool_result in tool_results:
                            tool_result["content"] = (
                                "Iteration limit reached, no more tool calls available."
                            )
                        tool_results.append(
                            {
                                "type": "text",
                                "text": (
                                    "Write your final answer now, based on the analysis "
                                    "so far. Do not call any more tools."
                                ),
                            }
                        )
                        final_instruction_included = True
                        local_fallback = True
                    local_api_messages.append({"role": "user", "content": tool_results})
                    if local_fallback:
                        break
                    continue

                if response.stop_reason == "refusal":
                    local_refusal = (
                        response_text or "Claude refused to answer this question."
                    )
                    break
                if response.stop_reason == "max_tokens":
                    if local_max_token_continuations < 2:
                        local_max_token_continuations += 1
                        local_api_messages.append(
                            {
                                "role": "user",
                                "content": "Continue your answer from where you stopped.",
                            }
                        )
                        continue
                    local_fallback = True
                    break
                if response.stop_reason == "pause_turn":
                    local_api_messages.append(
                        {
                            "role": "user",
                            "content": "Continue the analysis or write the final answer.",
                        }
                    )
                    continue
                if response.stop_reason != "tool_use":
                    local_final_answer = "\n\n".join(local_answer_parts).strip()
                    break
                local_error = "Claude returned an unsupported stop reason."
                break

            if not local_final_answer and not local_refusal and not local_error:
                local_fallback = True
            if local_fallback:
                if not final_instruction_included:
                    local_api_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Write your final answer now, based on the analysis so far. "
                                "Do not call any more tools."
                            ),
                        }
                    )
                _validate_messages(local_api_messages)
                fallback_response = client.messages.create(
                    model=selected_model,
                    max_tokens=request_max_tokens,
                    system=[
                        {"type": "text", "text": SYSTEM_PROMPT},
                        {
                            "type": "text",
                            "text": context,
                            "cache_control": {"type": "ephemeral"},
                        },
                    ],
                    messages=local_api_messages,
                )
                _usage_totals(usage_totals, fallback_response.usage)
                local_response_debug.append(
                    {
                        "iteration": len(local_response_debug) + 1,
                        "stop_reason": fallback_response.stop_reason,
                        "block_types": [
                            getattr(block, "type", "unknown")
                            for block in fallback_response.content
                        ],
                        "usage": {
                            key: getattr(fallback_response.usage, key, 0) or 0
                            for key in usage_totals
                        },
                    }
                )
                fallback_text = _text_blocks(fallback_response)
                if fallback_text:
                    local_answer_parts.append(fallback_text)
                local_final_answer = "\n\n".join(local_answer_parts).strip()
            return {
                "answer": local_final_answer,
                "refusal": local_refusal,
                "error": local_error,
                "debug": local_response_debug,
                "traces": local_tool_traces,
            }

        try:
            try:
                result = request_answer(api_messages)
            except anthropic.APIError as error:
                if "tool_use" not in str(error).lower() and "tool_result" not in str(
                    error
                ).lower():
                    raise
                st.session_state["chat_messages"] = _plain_text_history(
                    st.session_state["chat_messages"]
                )
                st.info("History was reset because of a technical error.")
                retry_messages = _plain_text_history(
                    st.session_state["chat_messages"]
                ) + [{"role": "user", "content": prompt}]
                result = request_answer(retry_messages)

            final_answer = result["answer"]
            refusal_message = result["refusal"]
            error_message = result["error"]
            response_debug = result["debug"]
            tool_traces = result["traces"]
            if refusal_message:
                st.error(refusal_message)
            elif error_message:
                st.error(error_message)
            elif final_answer:
                st.markdown(final_answer)
                st.session_state["chat_messages"].extend(
                    [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": final_answer},
                    ]
                )
            else:
                st.error("Claude returned no text. See the debug details below.")
                with st.expander("Claude response debug", expanded=True):
                    st.json(
                        {
                            "iterations": len(response_debug),
                            "responses": response_debug,
                        }
                    )
            for index, trace in enumerate(tool_traces, start=1):
                with st.expander(f"Analysis {index}: analyze_expenses", expanded=False):
                    st.code(trace["code"], language="python")
                    st.text(trace["output"])
            usage_totals["model"] = selected_model
            st.session_state["last_usage"] = usage_totals
        except anthropic.APIError as error:
            st.error(_api_error_message(error))
        except Exception as error:
            st.error(f"Unexpected error while contacting Claude: {error}")
