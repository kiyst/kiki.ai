# History RAG evaluation

The local `.kiki/history.sqlite3` database contains five Project Gutenberg
works covering U.S. history and political thought. The corpus has 1,540 paragraph-aware chunks,
all embedded with `qwen3-embedding:0.6b`.

Run a grounded question from the repository root:

```powershell
.\.venv\Scripts\python.exe -m kiki.cli --database .kiki\history.sqlite3 rag "Why did Paine reject hereditary succession?" --debug
```

`--debug` shows the allowlisted tool calls, verified sources, and whether hybrid
retrieval was used. Omit it for a cleaner answer.

For an ongoing session, run `kiki --database .kiki\history.sqlite3 run`, type
`/rag`, and ask the questions below. Use `/chat` when you want ordinary
conversation without document retrieval.

Useful evaluation questions:

1. Why did Paine distinguish society from government?
2. Why did Paine reject hereditary succession?
3. How does Federalist No. 10 propose controlling the effects of faction?
4. What weaknesses of the Articles of Confederation do the Federalist Papers identify?
5. Compare the purposes stated in the Constitution's preamble with the grievances in the Declaration.
6. What powers does the Constitution assign to Congress rather than the president?
7. According to the Beard history, what forces converged after 1763 to produce the Revolution?
8. Compare the Beard textbook's description of independence with the primary-source arguments in *Common Sense*.
9. Which claims are supported by multiple documents, and where do the sources differ in emphasis?
10. What does the corpus say about nuclear deterrence? (Expected result: insufficient evidence.)

The Beard history was published in 1921. Treat its framing as one historical
interpretation and ask Kiki to distinguish it from primary sources. Retrieval
can locate evidence; it does not make every source neutral, complete, or correct.
