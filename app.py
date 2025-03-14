# -*- coding: utf-8 -*-
"""MODEL.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1GnoWJ3-C6r41qyM-zEeybHrAvzlNezc8
"""

!pip install pinecone

import pandas as pd
import re
import torch
from transformers import BertTokenizer, BertForQuestionAnswering, Trainer, TrainingArguments, pipeline, BitsAndBytesConfig
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset, DataLoader
from imblearn.over_sampling import RandomOverSampler
from imblearn.under_sampling import RandomUnderSampler
from sentence_transformers import SentenceTransformer
import pinecone
from langchain.text_splitter import RecursiveCharacterTextSplitter

from pinecone import Pinecone

pc = Pinecone(api_key="pcsk_7BSh4K_8PTBDdDrHua2znwahVYYF7ksitNNrZ4KRvzGx7EMioskZXq98ZZMgLsT5BsKqVq")
index = pc.Index("biobert-medical")

"""# Load preprocessed datasets"""

combined_dataset = "/content/combined_dataset.csv"
df = pd.read_csv(combined_dataset)

"""# Balance Dataset"""

print(df.columns)

label_counts = df['label'].value_counts()
min_samples = label_counts.min()
max_samples = int(label_counts.mean())

undersampler = RandomUnderSampler(sampling_strategy={label: max_samples for label in label_counts[label_counts > max_samples].index})
df_under, _ = undersampler.fit_resample(df, df['label'])

oversampler = RandomOverSampler(sampling_strategy={label: min_samples for label in label_counts[label_counts < min_samples].index})
df_balanced, _ = oversampler.fit_resample(df_under, df_under['label'])

df_balanced.to_csv("biobert_balanced_data.csv", index=False)

"""# Tokenizer"""

model_name = "dmis-lab/biobert-base-cased-v1.1"
tokenizer = BertTokenizer.from_pretrained(model_name)

"""# Dataset Class"""

class QADataset(Dataset):
    def __init__(self, dataframe):
        self.data = dataframe

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        row = self.data.iloc[idx]
        encoded = tokenizer(row['input'], row['output'], truncation=True, padding='max_length', max_length=512, return_tensors='pt')
        return {
            'input_ids': encoded['input_ids'].squeeze(),
            'attention_mask': encoded['attention_mask'].squeeze(),
            'labels': encoded['input_ids'].squeeze()
        }

"""# Split data"""

train_df, test_df = train_test_split(df_balanced, test_size=0.1, random_state=42)
train_dataset = QADataset(train_df)
test_dataset = QADataset(test_df)

"""# Model with Quantization"""

!pip install bitsandbytes

!pip install --upgrade transformers

quantization_config = BitsAndBytesConfig(load_in_8bit=True)
model = BertForQuestionAnswering.from_pretrained(model_name, quantization_config=quantization_config)

"""# Apply LoRA Adapters

# Training Arguments
"""

training_args = TrainingArguments(
    output_dir="/mnt/data/biobert_finetuned",
    evaluation_strategy="epoch",
    save_strategy="epoch",
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    num_train_epochs=3,
    weight_decay=0.01,
    logging_dir="/mnt/data/logs"
)

!pip install peft

from peft import get_peft_model, LoraConfig, TaskType

# LoRA Configuration
lora_config = LoraConfig(
    task_type="SEQ_2_SEQ_LM",
    r=8,
    lora_alpha=32,
    lora_dropout=0.1,
    bias="none"
)

# Wrap the quantized model with LoRA
model = get_peft_model(model, lora_config)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=test_dataset
)

# Debugging: Print sample batch
for batch in train_dataset:
    print(batch.keys())
    break  # Print one batch structure

trainer.train()

"""# Save Model"""

model.save_pretrained("/mnt/data/biobert_finetuned")
tokenizer.save_pretrained("/mnt/data/biobert_finetuned")

"""# Vector Database (Pinecone)"""

from pinecone import Pinecone
pc = Pinecone(api_key="pcsk_7BSh4K_8PTBDdDrHua2znwahVYYF7ksitNNrZ4KRvzGx7EMioskZXq98ZZMgLsT5BsKqVq")

# List existing indexes
print(pc.list_indexes().names())

# Load the index
index = pc.Index("biobert-medical")

"""# Embedding Model"""

embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

"""# Use RecursiveCharacterTextSplitter for better context retrieval"""

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=50,
    separators=["\n\n", "\n", " ", ""]
)

"""# Structured Prompt"""

prompt = """
<|system|>
You are a helpful assistant that answers medical questions based on real information provided from different sources and in the context.
Give a rational and well-written response. If you don't have proper info in the context, answer "I don't know".
Respond only to the question asked.

<|user|>
Context:
{}
---
Here is the question you need to answer.

Question: {}
<|assistant|>
"""

"""# Interactive Test"""

user_input = input("User: ")
vectorized_input = embedding_model.encode(user_input)
context = index.query(namespace="ns1", vector=vectorized_input, top_k=1, include_metadata=True)

retrieved_text = context['matches'][0]['metadata']['text']
formatted_prompt = prompt.format(retrieved_text, user_input)

qa_pipeline = pipeline("text-generation", model=model, tokenizer=tokenizer)
answer = qa_pipeline(formatted_prompt)

"""# Check BioBERT's confidence"""

confidence_score = answer[0]['score'] if 'score' in answer[0] else 0.0

if confidence_score < 0.6:  # If confidence is low, use Zephyr-7B
    print("BioBERT is uncertain, using Zephyr-7B for a more conversational response...")
    answer = zephyr_pipeline(formatted_prompt)

print("AI response: ", answer[0]['generated_text'])

!pip install fastapi uvicorn transformers torch pinecone-client



from fastapi import FastAPI
from pydantic import BaseModel
from transformers import BertTokenizer, BertForQuestionAnswering, pipeline
import torch
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

# Initialize FastAPI app
app = FastAPI()

# Load BioBERT Model
MODEL_NAME = "dmis-lab/biobert-base-cased-v1.1"
tokenizer = BertTokenizer.from_pretrained(MODEL_NAME)
model = BertForQuestionAnswering.from_pretrained(MODEL_NAME).to("cuda" if torch.cuda.is_available() else "cpu")

# Load Embedding Model
embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# Load Pinecone Database
pc = Pinecone(api_key="pcsk_7BSh4K_8PTBDdDrHua2znwahVYYF7ksitNNrZ4KRvzGx7EMioskZXq98ZZMgLsT5BsKqVq")
index = pc.Index("biobert-medical")

# Define request format
class QueryRequest(BaseModel):
    question: str

@app.post("/generate")
async def generate_response(request: QueryRequest):
    prompt = request.question

    # Retrieve relevant documents from Pinecone
    query_embedding = embedding_model.encode(prompt).tolist()
    results = index.query(vector=query_embedding, top_k=5, include_metadata=True)

    # Construct context
    context = " ".join([match["metadata"]["text"] for match in results["matches"]])

    # Format question for BioBERT
    inputs = tokenizer.encode_plus(prompt, context, return_tensors="pt").to("cuda" if torch.cuda.is_available() else "cpu")
    
    # Generate response
    answer_start_scores, answer_end_scores = model(**inputs).values()
    answer_start = torch.argmax(answer_start_scores)
    answer_end = torch.argmax(answer_end_scores) + 1
    response_text = tokenizer.convert_tokens_to_string(tokenizer.convert_ids_to_tokens(inputs["input_ids"][0][answer_start:answer_end]))

    return {"response": response_text}
