from __future__ import annotations

import datetime

import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

API_BASE = "http://localhost:8000"

AGENTS: list[str] = [
    "Chief's Assistant",
    "Logistics",
    "Front Desk",
    "HR",
    "SysAdmin",
]

AGENT_ICONS: dict[str, str] = {
    "Chief's Assistant": "🎯",
    "Logistics":         "📦",
    "Front Desk":        "🏢",
    "HR":                "👥",
    "SysAdmin":          "🖥️",
}

LOG_OPTIONS: dict[str, str] = {
    "Logistics Log":  "logistics_log",
    "System Status":  "system_status",
    "HR Log":         "hr_log",
}

PRIORITY_COLOURS: dict[str, str] = {
    "Critical": "🔴",
    "High":     "🟠",
    "Normal":   "🟡",
    "Low":      "🟢",
}

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Virtual Office",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def api_health() -> bool:
    try:
        r = requests.get(f"{API_BASE}/", timeout=2)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


def stream_chat(agent: str, message: str, history: list[dict]) -> str:
    """POST to /chat/stream and yield accumulated text in Streamlit."""
    placeholder = st.empty()
    full_response = ""
    try:
        with requests.post(
            f"{API_BASE}/chat/stream",
            json={"agent": agent, "message": message, "history": history},
            stream=True,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                if chunk:
                    full_response += chunk
                    placeholder.markdown(full_response + "▌")
        placeholder.markdown(full_response)
    except requests.exceptions.ConnectionError:
        full_response = (
            "⚠️ Cannot reach the Virtual Office API.  \n"
            "Make sure the backend is running:  \n"
            "```\nuvicorn api.main:app --reload\n```"
        )
        placeholder.warning(full_response)
    except requests.exceptions.Timeout:
        full_response = "⚠️ Request timed out. Ollama may still be loading the model."
        placeholder.warning(full_response)
    return full_response


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🏢 Virtual Office")
    st.caption(f"📅 {datetime.date.today().strftime('%A, %B %d %Y')}")
    st.divider()

    st.subheader("Specialist")
    selected_agent: str = st.selectbox(
        "Route to",
        AGENTS,
        label_visibility="collapsed",
        format_func=lambda a: f"{AGENT_ICONS.get(a, '🤖')}  {a}",
    )

    st.divider()

    if api_health():
        st.success("API online", icon="✅")
    else:
        st.error("API offline — start backend", icon="🔴")

    with st.expander("ℹ️ Quick start"):
        st.code(
            "# 1 — install deps\npip install -r requirements.txt\n\n"
            "# 2 — start LLM\nollama serve\n\n"
            "# 3 — start API (project root)\nuvicorn api.main:app --reload\n\n"
            "# 4 — start UI (project root)\nstreamlit run ui/app.py",
            language="bash",
        )

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_chat, tab_logs, tab_quests = st.tabs(["💬 Chat", "📋 System Logs", "⚔️ Quest Board"])

# ═══════════════════════════════════════════════════════════════════
# CHAT TAB
# ═══════════════════════════════════════════════════════════════════
with tab_chat:
    icon = AGENT_ICONS.get(selected_agent, "🤖")
    st.header(f"{icon} {selected_agent}")

    # Per-agent message history in session state
    if "chat_histories" not in st.session_state:
        st.session_state.chat_histories: dict[str, list[dict]] = {}
    if selected_agent not in st.session_state.chat_histories:
        st.session_state.chat_histories[selected_agent] = []

    history = st.session_state.chat_histories[selected_agent]

    # Clear button
    if history and st.button("🗑️ Clear conversation", key="clear_chat"):
        st.session_state.chat_histories[selected_agent] = []
        st.rerun()

    # Render existing messages
    for msg in history:
        role_icon = icon if msg["role"] == "assistant" else "🧑‍💼"
        with st.chat_message(msg["role"], avatar=role_icon):
            st.markdown(msg["content"])

    # Input
    if prompt := st.chat_input(f"Message {selected_agent}…"):
        history.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="🧑‍💼"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar=icon):
            # Pass history minus the message we just added so the API doesn't double it
            reply = stream_chat(selected_agent, prompt, history[:-1])

        history.append({"role": "assistant", "content": reply})

# ═══════════════════════════════════════════════════════════════════
# SYSTEM LOGS TAB
# ═══════════════════════════════════════════════════════════════════
with tab_logs:
    st.header("📋 System Logs")

    col_nav, col_content = st.columns([1, 3], gap="medium")

    with col_nav:
        selected_log_label: str = st.radio(
            "Select log",
            list(LOG_OPTIONS.keys()),
            label_visibility="collapsed",
        )
        log_key = LOG_OPTIONS[selected_log_label]

        st.divider()
        with st.form("append_log_form"):
            st.caption("Append entry")
            entry_text = st.text_area("Content", height=120, label_visibility="collapsed")
            submitted = st.form_submit_button("Write", use_container_width=True)

        if submitted:
            if entry_text.strip():
                ts = datetime.datetime.now().strftime("**%Y-%m-%d %H:%M** — ")
                try:
                    r = requests.post(
                        f"{API_BASE}/logs/{log_key}",
                        json={"content": ts + entry_text, "append": True},
                        timeout=5,
                    )
                    if r.status_code == 200:
                        st.success("Entry written.")
                        st.rerun()
                    else:
                        st.error(f"API error {r.status_code}")
                except requests.exceptions.RequestException as exc:
                    st.error(f"Request failed: {exc}")
            else:
                st.warning("Nothing to write.")

    with col_content:
        try:
            r = requests.get(f"{API_BASE}/logs/{log_key}", timeout=5)
            if r.status_code == 200:
                st.markdown(r.json()["content"])
            else:
                st.warning(f"API returned {r.status_code}.")
        except requests.exceptions.RequestException:
            st.error("Cannot reach API. Ensure the backend is running.")

# ═══════════════════════════════════════════════════════════════════
# QUEST BOARD TAB
# ═══════════════════════════════════════════════════════════════════
with tab_quests:
    st.header("⚔️ Quest Board")

    col_form, col_board = st.columns([1, 2], gap="medium")

    with col_form:
        st.subheader("Post Quest")
        with st.form("new_quest_form"):
            q_title    = st.text_input("Title")
            q_assignee = st.selectbox("Assign to", AGENTS)
            q_priority = st.select_slider(
                "Priority",
                options=["Low", "Normal", "High", "Critical"],
                value="Normal",
            )
            post_btn = st.form_submit_button("Post Quest", type="primary", use_container_width=True)

        if post_btn:
            if q_title.strip():
                try:
                    r = requests.post(
                        f"{API_BASE}/quests/add",
                        json={"title": q_title, "assignee": q_assignee, "priority": q_priority},
                        timeout=5,
                    )
                    if r.status_code == 200:
                        st.success(f"Quest posted: {q_title}")
                        st.rerun()
                    else:
                        st.error(f"API error {r.status_code}")
                except requests.exceptions.RequestException as exc:
                    st.error(f"Request failed: {exc}")
            else:
                st.warning("Quest title is required.")

    with col_board:
        try:
            r = requests.get(f"{API_BASE}/quests", timeout=5)
            if r.status_code != 200:
                st.warning(f"API returned {r.status_code}.")
            else:
                quests: list[dict] = r.json().get("quests", [])

                open_quests = [q for q in quests if not q["done"]]
                done_quests = [q for q in quests if q["done"]]

                if not quests:
                    st.info("No quests yet — post one to get the team moving!")
                else:
                    if open_quests:
                        st.subheader(f"Open  ·  {len(open_quests)}")
                        for q in open_quests:
                            # Extract priority emoji from title if present
                            title: str = q["title"]
                            # Pull assignee / priority from title string if structured
                            emoji = "🟡"
                            for p, e in PRIORITY_COLOURS.items():
                                if f"Priority: {p}" in title:
                                    emoji = e
                                    break
                            st.markdown(f"{emoji} {title}")
                        st.divider()

                    if done_quests:
                        st.subheader(f"Completed  ·  {len(done_quests)}")
                        for q in done_quests:
                            st.markdown(f"✅ ~~{q['title']}~~")
        except requests.exceptions.RequestException:
            st.error("Cannot reach API. Ensure the backend is running.")
