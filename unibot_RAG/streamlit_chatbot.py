import os
from time import sleep

import openai
import streamlit as st
from dotenv import load_dotenv
from streamlit_chat import message

from unibot_RAG.api.unibot_langchain import unibot_RAG
from unibot_RAG.redis_db.redis_client import RedisClient
from unibot_RAG.utils.data_proc import extract_website_content

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# *****************************************************
# * Setup Environment
# *****************************************************

# Create a Redis client
unibot_redis_client = RedisClient.from_os_env()


vector_store = unibot_redis_client.vectorstore
unibot = unibot_RAG(vector_store)

if "website_content" not in st.session_state:
    st.session_state.website_content = None
if "process_clicked" not in st.session_state:
    st.session_state.process_clicked = False
if "chunks" not in st.session_state:
    st.session_state.chunks = []

# *****************************************************
# * Function Definition
# *****************************************************


def get_unibot_response(user_input):
    max_attempts = 3
    attemps = 0
    while attemps < max_attempts:
        try:
            response = unibot.get_response(user_input)

            return response

        except Exception as e:
            print(e)
            attemps += 1
    return {
        "answer": "uniBot: Sorry, I don't understand. Please try again.",
        "service": "None",
    }

def get_text():
    user_input = st.session_state["input"]
    is_triggered = st.session_state["is_triggered"]

    if is_triggered:
        st.session_state["is_triggered"] = 0
        return

    if user_input:
        unibot_result = get_unibot_response(user_input)

        # store the output
        st.session_state.past.append(user_input)
        st.session_state.unibot.append(unibot_result)

    st.session_state["is_triggered"] = 1


def clear_text():
    st.session_state["input"] = ""
    st.session_state["suggested_input"] = ""


def submit():
    get_text()
    clear_text()


def suggest():
    # question = qa_df.sample(n=1).Question.values[0]
    if "suggested_input" not in st.session_state:
        st.session_state[
            "suggested_input"
        ] = "Ask me anything on unibot knowledge base!"
    # else:
    #     st.session_state["suggested_input"] = "E.g.: " + question


def upvote(i):
    if not len(st.session_state["email_input"]):
        st.toast(":red[Please enter your email address!]", icon="❌")
        return

    most_similar_metadata = st.session_state["unibot"][i].get("metadata", "None")

    if most_similar_metadata is not None:
        most_similar_metadata["answer"] = st.session_state["unibot"][i].get(
            "source_document", "None"
        )
    # TODO: Add upvote to DB
    # res = add_row(
    #     *map(
    #         str,
    #         [
    #             st.session_state["past"][i],
    #             most_similar_metadata,
    #             st.session_state["unibot"][i]["result"],
    #             "upvote",
    #             "",
    #             st.session_state["email_input"],
    #         ],
    #     )
    # )
    # if res["status"] == "success":
    st.toast(":green[Thanks for your feedback!]", icon="✅")
    # else:
        # st.toast(":red[Something went wrong!]", icon="❌")


def downvote(i):
    if not len(st.session_state["email_input"]):
        st.toast(":red[Please enter your email address!]", icon="❌")
        return
    most_similar_metadata = st.session_state["unibot"][i].get("metadata", "None")

    if most_similar_metadata is not None:
        most_similar_metadata["answer"] = st.session_state["unibot"][i].get(
            "source_document", "None"
        )
    # TODO: Add downvote to DB
    # res = add_row(
    #     *map(
    #         str,
    #         [
    #             st.session_state["past"][i],
    #             most_similar_metadata,
    #             st.session_state["unibot"][i]["result"],
    #             "downvote",
    #             st.session_state[f"expected_output_{i}"],
    #             st.session_state["email_input"],
    #         ],
    #     )
    # )

    # if res["status"] == "success":
    st.toast(":green[Thanks for your feedback!]", icon="✅")
    # else:
        # st.toast(":red[Something went wrong!]", icon="❌")


# *****************************************************
# * UI Setup
# *****************************************************
with st.sidebar:
    st.markdown("# Welcome to UniBot 🙌")

    st.markdown(
        """
        Hi 您好!
        Welcome! I am UniBot.
        You can use Unitbot as chat agent for you knowledge base.
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        "1. You can ask Unibot on the topic related to the website you given.\n"
        "2. You can chat with Unibot, but if the topic is not related, Unibot will tell you 'I'm sorry, but I don't have enough information in my records to answer that.'"
    )

    st.markdown("👩‍🏫 Developers: Shih-Tzung Lai")
    st.markdown("---")
    st.markdown("## You can give rating for Unibot reply：")
    st.markdown("If Unibot's reply helps, give 👍 upvote for Unibot!")
    st.markdown(
        "If you don't think Unibot's reply correct or appropiate, Please provide your response and click 👎 downvote."
    )
    st.markdown("## 🌐 **Website Setup**")
    sample_sites = {
        "🧠 Wikipedia Artificial_intelligence": "https://en.wikipedia.org/wiki/Artificial_intelligence",
    }
    col1, col2 = st.columns(2)
    selected_sample = None
    with col1:
        for i, (name, url) in enumerate(list(sample_sites.items())[:2]):
            if st.button(name, key=f"sample_{i}"):
                selected_sample = url
                st.session_state.current_url = url
    
    with col2:
        for i, (name, url) in enumerate(list(sample_sites.items())[2:], 2):
            if st.button(name, key=f"sample_{i}"):
                selected_sample = url
                st.session_state.current_url = url
    default_value = selected_sample if selected_sample else st.session_state.get('current_url', '')
    website_url = st.text_input(
        "🔗 **Or enter your own URL:**",
        value=default_value,
        placeholder="https://medium.com/your-article-here",
        help="Enter any website URL you would like to chat with."
    )
    # Process button
    process_button = st.button("🚀 **Process Website**", type="primary")
    # Processing logic
    if process_button:
        if not website_url:
            st.markdown('<div class="status-error">❌ Please enter a website URL first!</div>', unsafe_allow_html=True)
        else:
            # Show processing status
            progress_placeholder = st.empty()
            
            try:
                with progress_placeholder:
                    st.markdown('<div class="status-info">🔄 Processing website content...</div>', unsafe_allow_html=True)
                
                # Extract website content
                st.session_state.website_content = extract_website_content(website_url)
                
                if st.session_state.website_content and len(st.session_state.website_content.strip()) > 50:
                    with progress_placeholder:
                        st.markdown('<div class="status-info">⚙️ Analyzing and chunking content...</div>', unsafe_allow_html=True)
                    
                    try: 
                        unibot_redis_client.ingest_document(st.session_state.website_content)
                        
                        st.session_state.process_clicked = True
                        st.session_state.current_url = website_url
                        
                        # Success message
                        progress_placeholder.markdown(
                            f'<div class="status-success">✅ Success! Found {len(st.session_state.chunks)} content chunks.<br/>🎯 Ready to chat!</div>',
                            unsafe_allow_html=True
                        )
                    except Exception as e:
                        progress_placeholder.markdown(
                            f'<div class="status-error">❌ Error processing website: {str(e)}<br/>Please try again or use a different URL.</div>',
                            unsafe_allow_html=True
                        )
                else:
                    progress_placeholder.markdown(
                        f'<div class="status-error">❌ Failed to extract content from website.{len(st.session_state.website_content.strip())}<br/>Please check the URL and try again.</div>',
                        unsafe_allow_html=True
                    )
            except Exception as e:
                progress_placeholder.markdown(
                    f'<div class="status-error">❌ Error processing website: {str(e)}<br/>Please try again or use a different URL.</div>',
                    unsafe_allow_html=True
                )
    
    # Current website info
    if st.session_state.process_clicked:
        st.markdown("---")
        st.markdown(
            f"""
            <div class="website-info">
                <p><strong>🌐 Current Website:</strong></p>
                <p>🔗 {st.session_state.current_url}</p>
                <p>📄 {len(st.session_state.chunks)} content chunks processed</p>
            </div>
            """, 
            unsafe_allow_html=True
        )                

# *****************************************************
# * State Management
# *****************************************************
for k in ("unibot", "past"):
    if k not in st.session_state:
        st.session_state[k] = []
st.session_state["is_triggered"] = 0
if "suggested_input" not in st.session_state:
    st.session_state["suggested_input"] = "Ask me some question in unibot knowledge base!"

st.text_input(
    "Please enter your email address:",
    placeholder="Press Enter to submit",
    key="email_input",
)

st.divider()

col_1_1, col_1_2, col_1_3 = st.columns((10, 2, 2))

with col_1_1:
    user_input = st.text_area(
        "input",
        value="",
        key="input",
        placeholder=st.session_state["suggested_input"],
        label_visibility="collapsed",
        on_change=submit,
        height=100,
    )

with col_1_2:
    st.button("Ask UniBot", on_click=submit)

with col_1_3:
    st.button("Question Lottery", on_click=suggest)

if st.session_state["unibot"]:
    n = len(st.session_state["unibot"])
    for i in range(n - 1, -1, -1):
        message(
            st.session_state["past"][i],
            is_user=True,
            key=f"ouruser_unibot_{i}",
        )

        ic, col_1_2_1, col_1_2_2 = st.columns((10, 1, 1))
        with ic:
            message(
                "\n".join(
                    [
                        st.session_state["unibot"][i]["answer"],
                    ]
                ),
                key=f"unibot_{i}",
            )
        with col_1_2_1:
            st.button("👍", key=f"upvote_{i}", on_click=upvote, args=(i,))
        with col_1_2_2:
            st.button("👎", key=f"downvote_{i}", on_click=downvote, args=(i,))

        col_1_1_1, col_1_1_2 = st.columns((3, 7))
        with col_1_1_1:
            st.toggle(
                "Show related answer in unibot knowledge.", key=f"toggle_{i}", value=False
            )
        with col_1_1_2:
            if st.session_state[f"toggle_{i}"]:
                st.write(f"{st.session_state[f'unibot'][i]['source_document']}")
        expected_output = st.text_area(
            "Correct Responses:",
            value="",
            key=f"expected_output_{i}",
            placeholder="Please provide your response here.",
            label_visibility="collapsed",
        )
