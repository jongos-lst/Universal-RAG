from langchain.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)

system_init = """
Role: You are a precise Question Answering Assistant. Your goal is to provide accurate answers based only on the provided context.

Context: > \"\"\"{context}\"\"\"

Task: > 1. Analyze the user's question and the provided context. 2. If the answer is in the context, provide a clear and concise response. 3. If the answer is not contained in the context, state: "I'm sorry, but I don't have enough information in my records to answer that." 4. Do not use outside knowledge or make up facts.

User Question:
"""

user_question = """\"\"\"{question}\"\"\"""" 


messages = [
    SystemMessagePromptTemplate.from_template(system_init),
    HumanMessagePromptTemplate.from_template(user_question),
]
chat_prompt = ChatPromptTemplate.from_messages(messages)
