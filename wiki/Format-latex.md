# LaTeX (`latex`)

## Tool and format

- **Tool**: LaTeX and related tools (pdfLaTeX, XeLaTeX, LuaLaTeX, etc.).
- **Full format name**: LaTeX source (`.tex`), plain text markup language for typesetting.
- **Format specification**: LaTeX is an extension of TeX; see e.g. the [LaTeX Project documentation](https://www.latex-project.org/help/documentation/).

## Origin and purpose

- **Origin**: Academic and technical writing, especially in mathematics, computer science, and linguistics.
- **Role in Flexiconv**: import LaTeX source as structural text (sections, paragraphs, lists) that can be converted into TEITOK-style TEI or other formats for corpus work.

Handled by `flexiconv/io/latex.py`.

## Minimal example

```tex
\documentclass{article}

\begin{document}

\section{Introduction}

This is a small LaTeX example.

\subsection{Bullets}

\begin{itemize}
  \item First point
  \item Second point
\end{itemize}

\end{document}
```

## Conversion semantics

- **Reading (`latex` input)**:
  - The current reader is **initial and conservative**:
    - Strips the preamble and processes only the body between `\begin{document}` and `\end{document}`.
    - Recognises `\section`, `\subsection`, `\subsubsection` at the start of a line and maps them to TEI `<head type="section|subsection|subsubsection">`.
    - Recognises `\begin{itemize}` / `\begin{enumerate}` and `\item`, mapping them to `<list><item>…</item></list>`.
    - Other non-empty lines are grouped into `<p>` paragraphs.
  - Inline markup (e.g. `\textbf`, `\emph`) and math are currently treated as plain text; they do **not yet** produce `<hi>` or formula elements.
  - The resulting TEI tree is stored under `document.meta["_teitok_tei_root"]`, so TEITOK/HTML/DOCX writers can reuse it verbatim.

- **Writing (`latex` output)**:
  - Not supported; conversion is one-way from LaTeX source into TEI/pivot.

## Notes and future extensions

- The goal is to provide a **semantic view** of LaTeX documents (sections, lists, basic structure), not to fully emulate LaTeX compilation.
- Support for commonly used linguistics packages and more sophisticated inline markup may be added in future iterations.

