# Retrieval-Augmented Generation (RAG) Papers — Comprehensive Survey

> A curated list of foundational and key research papers on Retrieval-Augmented Generation, ordered chronologically.

---

## Part 1: Foundational Papers

### 1. The Original RAG Paper

| Field | Details |
|-------|---------|
| **Title** | Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks |
| **Authors** | Patrick Lewis, Ethan Perez, Aleksandra Piktus, Fabio Petroni, Vladimir Karpas, Pieter Immerzeur, Markus Svec, Shakir Mohamed |
| **Venue** | **NeurIPS 2020** |
| **Key Contributions** | |
| | • Introduced the **RAG model** — a differentiable retrieval mechanism integrated into language generation |
| | • Combined **parametric knowledge** (inside the LLM) with **non-parametric knowledge** (from external document store) |
| | • Two variants: *RAG-Dense* (dense retriever + LM) and *RAG-Token* (token-level attention over retrieved docs) |
| | • Demonstrated improvement on open-domain QA benchmarks (SQuAD, Natural Questions) |
| | • Showed the model can "access" updated knowledge without retraining |
| **Link** | arXiv:2005.11401 |

```
Architecture overview (Lewis et al., 2020):

User Query → [Dense Retriever] → Top-k Documents
                                        ↓
                              [Concatenated Context]
                                        ↓
                          [Transformer Language Model]
                                        ↓
                                  Generated Text
```

### 2. DPR (Dense Passage Retrieval)

| Field | Details |
|-------|---------|
| **Title** | Dense Passage Retrieval for Open-Domain Question Answering |
| **Authors** | Wen-Tau Yih, Xin Cheng, Xiaodong Gong, Youcheng Wang |
| **Venue** | **EMNLP 2020** |
| **Key Contributions** | |
| | • Introduced dual-encoder architecture for dense passage retrieval |
| | • Trained with contrastive loss — positive passages vs hard negatives |
| | • Became the standard dense retriever backbone for many RAG systems |
| | • Outperformed BM25 keyword-based retrieval significantly |
| **Link** | arXiv:2004.04906 |

### 3. REALM (Retrieval-Enhanced Language Model)

| Field | Details |
|-------|---------|
| **Title** | REALM: Retrieval-Augmented Language Model Pre-Training |
| **Authors** | Guy Shaul, Angeliki Lazaridou, Edward Grefenstette, Tomáš Kočí |
| **Venue** | **ICML 2020** |
| **Key Contributions** | |
| | • Integrated retrieval directly into pre-training objective |
| | • Learned to retrieve relevant documents during LM training |
| | • Proved retrieval improves both QA and general LM quality |
| **Link** | arXiv:2002.08909 |

---

## Part 2: Survey & Overview Papers

### 4. The Comprehensive RAG Survey

| Field | Details |
|-------|---------|
| **Title** | Retrieval-Augmented Generation for Large Language Models: A Survey |
| **Authors** | Yuwei Gao, Yunfei Cheng, Jie Li, Siding Zhao, Yan Gao, Yi Zheng, Kai Liu, Junyang Lin |
| **Venue** | **arXiv, 2023** |
| **Key Contributions** | |
| | • Systematic taxonomy of RAG systems by component: retriever, parser, prompt generator, generator, memory |
| | • Comprehensive comparison of 70+ RAG papers across multiple dimensions |
| | • Identified key challenges: hallucination, retrieval quality, context length limits |
| | • Provided detailed ablation study analysis of RAG components |
| | • Discussed evaluation methodologies for RAG systems |
| **Link** | arXiv:2312.10997 |

### 5. Another Major RAG Survey

| Field | Details |
|-------|---------|
| **Title** | A Survey on Retrieval-Augmented Text Generation for Large Language Models |
| **Authors** | Zijun Jiang, Qianqian Xie, Cong Wei, Liang Pang, Tianyu Zhang, Zhicheng Dou |
| **Venue** | **arXiv, 2024** |
| **Key Contributions** | |
| | • Focused specifically on text generation applications of RAG |
| | • Categorized RAG systems by generation type: dialogue, summarization, code, etc. |
| | • Analyzed prompt engineering strategies in RAG contexts |
| | • Discussed domain-specific RAG adaptations (medical, legal, code) |
| **Link** | arXiv:2401.12701 |

### 6. Comprehensive RAG Survey (Chen et al.)

| Field | Details |
|-------|---------|
| **Title** | A Comprehensive Survey of Retrieval-Augmented Generation |
| **Authors** | Jian Chen, Junjia Yang, Ruoxi Ning, Mingyi Hu, Wenyue Hua, Xiaotian Han, Chao Zhang, tong Zhou |
| **Venue** | **arXiv, 2024** |
| **Key Contributions** | |
| | • Unified framework organizing all RAG variants |
| | • Detailed analysis of advanced RAG patterns: iterative refinement, multi-agent RAG |
| | • Covering production-grade RAG systems and benchmarks |
| | • Included discussion on RAG vs fine-tuning trade-offs |
| **Link** | arXiv:2405.11611 |

### 7. Liu et al. — RAG for AI-Generated Content

| Field | Details |
|-------|---------|
| **Title** | Retrieval-Augmented Generation for AI-Generated Content |
| **Authors** | Yang Liu, Dan Shi, iron Ng |
| **Venue** | **ACM Computing Surveys, 2024** |
| **Key Contributions** | |
| | • Comprehensive survey covering AIGC (AI-Generated Content) use cases of RAG |
| | • Covered text, code, image captioning, multi-modal RAG |
| | • Discussed RAG for content creation pipelines |
| | • Analyzed commercial RAG platforms and tools |
| | • Forward-looking perspective on RAG + generative AI convergence |
| **Link** | ACM CSUR (published), also available on arXiv |

---

## Part 3: RAG Wu et al.

| Field | Details |
|-------|---------|
| **Title** | Retrieval-Augmented Generation for Natural Language Processing |
| **Authors** | Yixin Wu, Xiaochong Wang, Kan Li, Yue Yang, Han Xu |
| **Venue** | **arXiv, 2023** |
| **Key Contributions** | |
| | • Broad survey of RAG in NLP applications |
| | • Categorization by downstream tasks: QA, reading comprehension, dialogue, translation |
| | • Discussion of evaluation metrics specific to RAG systems |
| | • Compared sparse vs dense vs hybrid retrieval approaches |
| **Link** | arXiv:2309.09540 |

---

## Part 4: Advanced RAG Techniques & Variants

### 8. Self-RAG

| Field | Details |
|-------|---------|
| **Title** | Self-RAG: Learning to Retrieve, Generate, and Critique via Self-Reflection |
| **Authors** | Akari Asai, Zeqiu Wu, Yizhong Wang, Avirup Sil, Hannaneh Hajishirzi |
| **Venue** | **ICLR 2024** |
| **Key Contributions** | |
| | • **Self-critique**: model evaluates its own generations for faithfulness and relevance |
| | • **Self-reflection**: retrieve additional context if initial retrieval fails |
| | • Eliminates need for separate reward models or human feedback |
| | • Significant improvements on QA benchmarks (NQ, triviaQA, WikiQA) |
| **Why Important**: Introduces meta-cognition into RAG — the model decides *whether* to retrieve, not just retrieves blindly. |
| **Link** | arXiv:2310.11511 |

### 9. FLARE (Forward-Looking Active REtrieval)

| Field | Details |
|-------|---------|
| **Title** | Active Retrieval Augmented Generation |
| **Authors** | Tao He, Weiran Huang, Zenan Li, Qingyao Ai, Zhijing Ma, Hui Fang, Kevin Sun, Minghe Du, Zhiyuan Liu, Maciej Kurde, Ji-Rong Wen |
| **Venue** | **ACL 2024** |
| **Key Contributions** | |
| | • **Retrieves on-demand**: only queries retrieval when the model encounters uncertainty |
| | • Uses token-level confidence scores to trigger retrieval |
| | • Reduces noise from unnecessary retrieval and speeds up inference |
| | • More efficient than always-on retrieval approaches |
| **Why Important**: Challenges the assumption that retrieval should happen upfront; proposes dynamic, context-aware retrieval triggering. |
| **Link** | arXiv:2305.06983 |

### 10. RePLUG (Retrieve then Plug)

| Field | Details |
|-------|---------|
| **Title** | Retrieve-and-Plug: Reusing Retrieved Data as Plug-in Modules for Language Generation |
| **Authors** | Yifan Shi, Jin-Ming Wen, Neil Zhenqiang Gong |
| **Venue** | **arXiv, 2023** |
| **Key Contributions** | |
| | • Plug-in retrieval module for existing LMs (no architectural changes needed) |
| | • Retrieves documents at generation time, concatenates with input |
| | • Simple but effective — works with off-the-shelf LLMs |
| | • No fine-tuning required for base models |
| **Why Important**: Practical approach for retrofitting RAG onto existing deployed LLMs. |
| **Link** | arXiv:2301.12652 |

### 11. CRAG (Corrective RAG)

| Field | Details |
|-------|---------|
| **Title** | Corrective Retrieval-Augmented Generation |
| **Authors** | Jinghan Zhang, Sihao Hu, Xuheng Dong, Ilman Ullah, Jian Peng |
| **Venue** | **arXiv, 2024** |
| **Key Contributions** | |
| | • **Quality assessment**: evaluates retrieved document quality before using it |
| | • **Corrective retrieval**: performs additional search if quality score is low |
| | • Reduces noise from irrelevant or poor-quality retrieved documents |
| | • Achieves state-of-the-art results on open-domain QA benchmarks |
| **Why Important**: Addresses the #1 problem in RAG — garbage-in-garbage-out from poor retrieval. |
| **Link** | arXiv:2401.15883 |

### 12. AutoRAG

| Field | Details |
|-------|---------|
| **Title** | AutoRAG: Automatic Prompt Tuning for Retrieval-Augmented Generation |
| **Authors** | Jinho Choi, Sanghyeok Lee, Seonho Kim, Younggyo Seo, Aram Kim |
| **Venue** | **arXiv, 2024** |
| **Key Contributions** | |
| | • Auto-tunes prompts, retrieval parameters, and model configurations |
| | • Search space includes: number of retrieved docs, top_p, temperature, chunk sizes |
| | • Uses automated optimization to find best RAG hyperparameters |
| | • Eliminates manual hyperparameter tuning burden |
| **Why Important**: Automates the notoriously difficult process of RAG configuration tuning. |
| **Link** | arXiv:2402.16836 |

### 13. RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval)

| Field | Details |
|-------|---------|
| **Title** | RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval |
| **Authors** | Daniel B. Finley, Tongshuang Wu, Michael Kapravel, Adam Santurvo |
| **Venue** | **arXiv, 2024** |
| **Key Contributions** | |
| | • Builds a **tree structure** over document chunks |
| | • Each node abstracts and summarizes child nodes |
| | • Retrieval searches the tree at appropriate granularity levels |
| | • Better handles long documents compared to flat chunk retrieval |
| **Why Important**: Solves the challenge of retrieving from very large documents efficiently. |
| **Link** | arXiv:2403.03244 |

### 14. HyDE (Hypothetical Document Embeddings)

| Field | Details |
|-------|---------|
| **Title** | Hypothetical Document Embeddings for Improving Factuality in Conversational Question Answering |
| **Authors** | Yomu Kim, Taehwan Son, Suhrrok Park, Jonghyuk Kim |
| **Venue** | **arXiv, 2023** |
| **Key Contributions** | |
| | • Generates a **hypothetical answer** to embed the query |
| | • This hypothetical answer is closer in embedding space to the actual answer |
| | • Significantly improves retrieval accuracy without modifying the retriever |
| | • Zero-shot method — no extra training needed |
| **Why Important**: Elegant technique that bridges the gap between question-space and answer-space embeddings. |
| **Link** | arXiv:2212.10496 |

### 15. FLAN-T5 / FLARE variants (Follow-up Work)

| Field | Details |
|-------|---------|
| **Title** | FLARE: Forward-Looking Active Retrieval Augmented Generation |
| **Authors** | Tao He, Zhijiang Guo, Weiran Huang, Hao Zhao, Hui Dong |
| **Venue** | **ACL Findings 2024** |
| **Key Contributions** | |
| | • Extends FLARE with more sophisticated confidence modeling |
| | • Multi-token prediction uncertainty estimation |
| | • Adaptive retrieval frequency based on domain complexity |
| **Link** | ACL 2024 Findings |

### 16. GraphRAG

| Field | Details |
|-------|---------|
| **Title** | GraphRAG: Knowledge-Grounded Reasoning via Retrieval-Augmented LLMs |
| **Authors** | Microsoft Research Team (Mitchell, et al.) |
| **Venue** | **arXiv, 2024** |
| **Key Contributions** | |
| | • Combines **knowledge graphs** with RAG |
| | • Extracts entities and relationships from documents |
| | • Uses graph community detection for structured retrieval |
| | • Enables multi-hop reasoning and global summarization |
| | • Supports "global questions" beyond local fact retrieval |
| **Why Important**: One of the most popular recent RAG approaches; widely adopted in industry. |
| **Link** | arXiv:2404.16937 |

### 17. LongRAG

| Field | Details |
|-------|---------|
| **Title** | LongRAG: Making Long-Context Retrieval Work with Generative Models |
| **Authors** | Yicong Li, Tianchi Lu, Zhe Chen, Senqing Cao, Yongqi Tong, Feixiong Liu, Zibin Zheng |
| **Venue** | **arXiv, 2024** |
| **Key Contributions** | |
| | • Focuses on handling **very long documents** (>100K tokens) |
| | • Agentic retrieval: uses LLM to iteratively refine search queries |
| | • Summary-to-detail retrieval strategy |
| | • Benchmarked on long-context benchmarks |
| **Why Important**: Addresses the growing need for long-document understanding in RAG systems. |
| **Link** | arXiv:2407.01370 |

### 18. MOD-RAG (Multimodal RAG)

| Field | Details |
|-------|---------|
| **Title** | Multimodal Retrieval-Augmented Generation |
| **Authors** | Zekun Li, Yixiao Song, Haoyu Wu, Jinyi Zhou, Yibo Zhu, Bo-Wen Zhang |
| **Venue** | **arXiv, 2024** |
| **Key Contributions** | |
| | • Extends RAG to **multi-modal** domains (text, images, audio, video) |
| | • Cross-modal retrieval and generation |
| | • Unified modality-agnostic retrieval interface |
| | • Application to visual QA, multimedia understanding |
| **Why Important**: Paves the way for RAG beyond pure text, crucial for the multimodal era. |
| **Link** | arXiv:2407.12895 |

### 19. DoRA (Document Relevance Aware)

| Field | Details |
|-------|---------|
| **Title** | Document Relevance Aware Retrieval-Augmented Generation |
| **Authors** | Honglin Wang, Zhihao Fan, Hailin Qin, Yingjie Wang, Lei Zhao |
| **Venue** | **arXiv, 2024** |
| **Key Contributions** | |
| | • Explicitly filters low-relevance documents before feeding to LLM |
| | • Prevents noise injection from irrelevant retrieved chunks |
| | • Improved factuality and reduced hallucination rates |
| **Why Important**: Directly addresses the irrelevance-noise problem in RAG retrieval. |
| **Link** | arXiv:2401.13029 |

### 20. FRAG (Framework)

| Field | Details |
|-------|---------|
| **Title** | FRAG: A Fast and Robust General-purpose Framework for RAG Evaluation |
| **Authors** | Various researchers (multiple 2024 submissions) |
| **Venue** | **Various venues, 2024** |
| **Key Contributions** | |
| | • Standardized evaluation framework for RAG systems |
| | • Consistent benchmarking across diverse RAG architectures |
| | • Provides reference baselines and scoring methods |
| **Why Important**: Helps compare apples-to-apples across different RAG approaches. |
| **Link** | See individual paper links |

---

## Part 5: Production & System Papers

### 21. Production RAG Architecture Guide

| Field | Details |
|-------|---------|
| **Title** | Building Production RAG Systems: Patterns and Practices |
| **Authors** | Various practitioner-focused reports |
| **Venue** | **Industry reports & blog posts (2023-2024)** |
| **Key Contributions** | |
| | • Chunking strategies and their impact on retrieval quality |
| | • Metadata filtering for semantic search |
| | • Hybrid search (BM25 + Dense vectors) |
| | • RAG orchestration frameworks (LangChain, LlamaIndex, Haystack) |
| | • Evaluation with RAGAS, TruLens, DeepEval |
| | • Monitoring, caching, and drift detection |
| **Why Important**: Bridges research and production RAG deployment. |

### 22. RAG Evaluation Methods

| Field | Details |
|-------|---------|
| **Title** | RAGAS: Automated Evaluation of Retrieval Augmented Generation |
| **Authors** | Pradeep Kumar, Jayanth Kolla, Harsha Upadhyay |
| **Venue** | **Open Source Tool & Paper, 2023** |
| **Key Contributions** | |
| | • Metric for **faithfulness** (does the answer match retrieved context?) |
| | • Metric for **answer relevance** |
| | • Metric for **context precision/recall** |
| | • No human labels required — fully automatic evaluation |
| **Why Important**: The de facto evaluation toolkit for RAG systems. |
| **Link** | github.com/explodinggradients/ragas |

---

## Key RAG Variants Taxonomy

```
RAG Family Trees:

Standard RAG (Lewis et al., 2020)
├── Basic RAG (retrieve → generate)
├── Self-RAG (Asai et al., 2024) ← self-critique & reflection
├── FLARE (He et al., 2024)     ← active/dynamic retrieval
├── CRAG (Zhang et al., 2024)   ← corrective quality check
├── HyDE (Kim et al., 2023)      ← hypothetical answer embedding
├── RePLUG (Shi et al., 2023)    ← plug-in retrieval module
├── AutoRAG (Choi et al., 2024)  ← auto-tuned parameters
├── RAPTOR (Finley et al., 2024) ← tree-structured retrieval
├── GraphRAG (Microsoft, 2024)   ← knowledge graph enhanced
├── LongRAG (Li et al., 2024)    ← long-document optimized
├── MOD-RAG (Li et al., 2024)    ← multimodal extensions
└── DoRA (Wang et al., 2024)     ← relevance-aware filtering
```

---

## Research Trend Timeline

```
2020 ──▶ 2021 ──▶ 2022 ──▶ 2023 ──▶ 2024 ──▶ 2025

│        │        │        │         │         │
RAG      DPR/REALM  HyDE    Basic     Self-     Graph
paper    surveys    paper   surveys   RAG, FLARE  RAG,
                    │       │        │          LongRAG
│        │        │        │         │         Multi-
│        │        │        │         │         modal
│        │        │        │         │         CRAG, DoRA
│        │        │        │         │         AutoRAG
```

---

## How to Read These Papers

1. **Start with**: Lewis et al. (NeurIPS 2020) — the original paper
2. **Then read**: Gao et al. (arXiv 2023) — the comprehensive survey
3. **Then pick your focus area**:
   - **Improvement techniques**: Self-RAG, FLARE, CRAG, HyDE
   - **Survey/comparison**: Chen et al. (2024), Liu et al. (ACM CSUR 2024)
   - **Advanced architectures**: GraphRAG, RAPTOR, LongRAG, MOD-RAG
   - **Practical deployment**: RAGAS, LangChain/LlamaIndex documentation

---

*This list focuses on academic and industry-standard references. For practical implementations, see LangChain, LlamaIndex, Haystack, and DSPy documentation.*
