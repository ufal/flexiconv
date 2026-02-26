## Formats in scope and mapping strategies

This document sketches the **format landscape** for Flexiconv and describes how each group of formats should be mapped:

- Into the **Flexiconv Pivot Model (FPM)**.
- Into and out of **TEITOK’s TEI format**.

It is deliberately high-level; concrete field-level mappings will be refined per format module.

### 1. TEI-based formats

#### 1.1 TEITOK TEI

- **Role**:
  - Primary **authoritative format** for TEITOK-based corpora.
  - Key target for most conversions.
- **Characteristics**:
  - TEI-conformant XML with TEITOK conventions:
    - `<tok>` and `<dtok>` with rich attributes (lemma, upos/xpos, feats, head, deprel, deps, `reg`, `expan`, etc.).
    - `<s>` (including empty `<s/>` with `sameAs` token lists), `<u>`, `<name>`, `<seg>`, structural `<div>`, `<p>`, `<pb/>` and other milestone-like elements for pages/columns/verse lines, etc.
    - TEITOK metadata and project settings.
- **Mapping to FPM**:
  - Tokens: `<tok>` / `<dtok>` → `tokens` layer nodes; `xml:id` → `tokid`; attributes → token features.
  - Sentences: `<s>` (including empty `<s/>` elements with `sameAs`) → `sentences` layer:
    - For milestone-style `<s/>`, the `sameAs` token IDs are converted into explicit token-range anchors on the sentence node.
  - Utterances: `<u>` → `utterances` layer, with speaker and time features if available.
  - Inline annotations: `<name>`, `<seg>`, etc. → `spans` in named layers (e.g. `named_entities`, `segments`).
  - Structural hierarchy: `<div>`, `<p>`, etc. → `structure` layer nodes/edges.
  - Metadata: TEI header + TEITOK project settings → document `meta` / `attrs`.
- **Mapping from FPM to TEITOK**:
  - FPM `tokens`, `sentences`, `utterances`, `spans`, and `structure` are serialized back into TEI elements, preserving IDs and attributes.
  - Where needed to avoid crossing hierarchies in XML, sentence/page/column/verse boundaries are rendered as milestone or empty elements (e.g. `<s/>` + `sameAs`, `<pb/>`) even though they are fully explicit nodes in FPM.
  - Must support round-trip tests with real TEITOK projects.

#### 1.2 TEI-CORPO TEI

- **Role**:
  - TEI-based format for **spoken corpora**, used by TEI-CORPO.
- **Characteristics**:
  - Emphasizes:
    - Utterances and tier structure.
    - Time alignment to media.
    - Speaker information.
- **Mapping to FPM**:
  - Utterances: `<u>` → `utterances` layer with time and token anchors.
  - Tiers: TEI-CORPO-specific tier structures → dedicated layers with tier metadata.
  - Tokens: `<w>` or equivalent token elements → `tokens` layer.
  - Time: timeline and media references → `timelines` and `media` in FPM.
- **Bridge to TEITOK**:
  - TEI-CORPO TEI can be converted to TEITOK TEI either:
    - Directly (Python-native), or
    - Via TEI-CORPO + teitok-tools where that is easier, then imported back into FPM.

#### 1.3 Generic TEI

- **Role**:
  - Baseline TEI imports from corpora that are not TEITOK or TEI-CORPO-specific.
- **Characteristics**:
  - Heterogeneous; may require configuration (e.g. which elements correspond to paragraphs, sentences, tokens).
- **Mapping to FPM**:
  - Use a configurable **mapping profile** that specifies:
    - Which elements represent tokens, sentences, utterances, etc.
    - How to interpret attributes and IDs.
  - Populate `structure`, `tokens`, `sentences`, and possibly `utterances` layers accordingly.
  - TEI inline markup → `spans`.

### 2. Treebank and NLP formats

#### 2.1 CoNLL-U

- **Role**:
  - Standard UD treebank format.
- **Characteristics**:
  - Token lines with ID, form, lemma, UPOS, XPOS, FEATS, HEAD, DEPREL, DEPS, MISC.
  - Comments for metadata (`# sent_id`, `# text`, `# newdoc id`, etc.).
- **Mapping to FPM**:
  - Each token line → `tokens` node.
  - Sentence boundaries → `sentences` nodes with `sent_id` and `text`.
  - Dependency relations:
    - Either stored as token features (`head`, `deprel`) or
    - Explicit `syntax` edges (preferred for complex structures).
  - Document-level metadata → FPM `meta` and document-level `attrs`.
- **Mapping to TEITOK**:
  - Via FPM:
    - `tokens` + `sentences` + `syntax` → TEITOK `<tok>` attributes and sentence/segment elements.
  - Must align with existing `teitok-tools` conversions for compatibility.

#### 2.2 VRT / TCF / Manatee / KonText-related formats

- **Role**:
  - Corpus back-end formats used in tools like KonText, TCF, or verticalized text corpora.
- **Mapping to FPM**:
  - Treat as token sequences with possibly sentence and structural markers.
  - Use `tokens` and `sentences` layers, plus `structure` for document divisions.
- **Mapping to TEITOK**:
  - Follow the semantics of `teitok-tools` (`manatee2teitok.pl`, `teitok2vrt.pl`, `teitok2tcf.pl`) as the reference.

### 3. Spoken corpora and transcripts

#### 3.1 ELAN (`.eaf`)

- **Role**:
  - Rich multi-tier annotation for audio/video.
- **Characteristics**:
  - Multiple tiers with time-aligned annotations.
  - Tier types (symbolic association, time subdivision, etc.).
  - Linked media files.
- **Mapping to FPM**:
  - Media paths → `media`.
  - Time axis → `timelines`.
  - Tiers → dedicated layers with:
    - Tier metadata nodes.
    - Annotation nodes anchored to timelines and (optionally) tokens.
  - Speaker/participant info → utterance features or separate participant layers.
- **Mapping to TEITOK**:
  - Either:
    - Direct mapping ELAN → FPM → TEITOK TEI (with spoken extensions), or
    - Via TEI-CORPO and its CLIs when appropriate.

#### 3.2 Praat TextGrid

- **Role**:
  - Interval- and point-based annotations for audio.
- **Mapping to FPM**:
  - Each tier → a layer or tier node with associated annotation nodes.
  - Annotations anchored to a timeline with start/end times.
  - Optional token alignment if corresponding TEITOK tokens exist.
- **Mapping to TEITOK / TEI-CORPO**:
  - Use FPM utterance and tier layers.
  - Optionally call TEI-CORPO converters for complex cases.

#### 3.3 Exmaralda, Transcriber (`.trs`), CLAN/CHAT, SRT, raw transcripts

- **Role**:
  - Various transcription formats for spoken data.
- **Mapping to FPM**:
  - Identify:
    - Turns/utterances → `utterances` layer (with speaker, time).
    - Tokens → `tokens` layer (with segmentation rules).
    - Overlaps and multiple channels → tier or channel-specific layers.
- **Mapping to TEITOK**:
  - Follow the semantics encoded in `teitok-tools` (e.g. `trs2teitok.pl`, `chat2teitok.pl`, `srt2teitok.pl`) but expressed via FPM.

### 4. OCR/HTR and manuscript formats

#### 4.1 hOCR, PAGE XML, TEITOK page flows

- **Role**:
  - Represent page layout, regions, lines, and token bounding boxes.
- **Mapping to FPM**:
  - `pages` layer with `"page"` nodes including:
    - Page number, image reference, bounding boxes.
  - `regions` / `lines` layers for layout elements, with spatial coordinates.
  - Tokens linked to layout via:
    - Node anchors (page/line region IDs).
    - Spatial coordinates (where available).
- **Mapping to TEITOK**:
  - TEITOK’s page/region structures are derived from `pages`/`regions` layers and associated tokens.

#### 4.2 PDF, image-only sources (via OCR/HTR)

- **Role**:
  - Primary sources for OCR/HTR pipelines, usually consumed through intermediate formats (hOCR, PAGE, ALTO).
- **Strategy**:
  - Flexiconv does not run OCR/HTR itself; it imports from OCR/HTR output formats.
  - The mapping is therefore between those intermediate XML formats and FPM/TEITOK.

### 5. Word processing and office formats

#### 5.1 DOCX (Word)

- **Role**:
  - Common authoring and legacy format for texts.
- **Mapping to FPM**:
  - Extract:
    - Paragraphs, headings → `structure` layer.
    - Text runs → `tokens` layer (with configurable tokenization).
    - Styles (bold, italic, footnotes, comments) → spans or features.
  - Preserve minimal structural information needed to reconstruct a TEI-compliant document.
- **Mapping to TEITOK**:
  - Use FPM `structure` + `tokens` → TEI/TEITOK text; styles can be mapped to TEI inline markup where desirable.
  - Existing `docx2tei.py` script in `teitok-tools` provides a reference mapping.

#### 5.2 Other office formats (ODT, etc.)

- **Strategy**:
  - Initially out of scope; can be added later via the same principles as DOCX.

### 6. Annotation formats

#### 6.1 brat standoff

- **Role**:
  - Span and relation annotations in text.
- **Characteristics**:
  - Separate `.ann` files with:
    - Text-bound annotations (spans).
    - Relations between annotations.
    - Attributes on annotations.
- **Mapping to FPM**:
  - Base text (usually from a `.txt` file) → `tokens` and `sentences`.
  - brat entities → `spans` in an annotation layer, anchored by character or token offsets.
  - brat relations → `edges` between nodes representing the relevant spans or events.
- **Mapping to TEITOK**:
  - Where appropriate, spans become TEI inline elements (e.g. `<name type="...">`), or are stored as standoff annotations in TEITOK-compatible extensions.

#### 6.2 WebAnno / INCEpTION formats

- **Role**:
  - Complex annotation projects with multiple layers.
- **Mapping to FPM**:
  - For token-level corpora:
    - Import token and sentence structure.
    - Each WebAnno layer → dedicated FPM layer with spans and/or edges.
  - Use annatto’s WebAnno importer/exporter as a reference for field semantics.
- **Mapping to TEITOK**:
  - Inject into TEITOK as:
    - Inline markup where appropriate.
    - Extra attributes on `<tok>` / `<dtok>` nodes.
    - Separate annotation layers if TEITOK configuration allows.

#### 6.3 ANNIS / graphANNIS / SaltXML

- **Role**:
  - Graph-based corpus models and serialization formats.
- **Mapping to FPM**:
  - Graph nodes → `graphannis` layer nodes with features and optional anchors.
  - Graph edges → `graphannis` layer edges.
  - SaltXML and graphANNIS field semantics → preserved in features and layer metadata.
- **Mapping to TEITOK**:
  - Subset of graphs that correspond to token, sentence, and structural relations can be materialized as TEI elements and token annotations.

#### 6.4 Toolbox, table-based, XLSX

- **Role**:
  - Linguistic fieldwork, structured dictionary or glossed text formats, spreadsheet-based annotations.
- **Mapping to FPM**:
  - Rows and fields → nodes and features in dedicated layers (e.g. interlinear glossing tiers).
  - Where texts are present, map them to `tokens` and link annotation rows via edges.
- **Mapping to TEITOK**:
  - Use TEI constructs for interlinear glossed text where appropriate, mapping FPM layers to TEI `<seg>`, `<w>`, and tier-specific elements.

### 7. Corpus back-end and export formats

#### 7.1 KonText / Manatee, TXM, Lexico, IRAMUTEQ, etc.

- **Role**:
  - Targets for export from TEITOK and TEI-CORPO (and thus from Flexiconv).
- **Strategy**:
  - Treat these as **searchable corpus back-ends**:
    - FPM → TEITOK or TEI-CORPO → indexed vertical/registry formats (KonText/Manatee, TXM, Lexico, IRAMUTEQ), following existing tools as the semantic reference.
    - Where practical, Flexiconv may also **read existing indexed corpora directly** (e.g. vertical files + registry metadata) into FPM, so that already-indexed corpora can be converted without re-importing raw sources.
  - Flexiconv implementations:
    - Either marshal data directly from FPM to the back-end format (vertical + metadata suitable for indexing).
    - Or call existing tools as backends (e.g. teitok-tools, TEI-CORPO, annatto) where that is safer.

### 8. Strategy for incremental coverage

- **Phase 1 – Core formats**:
  - TEITOK, CoNLL-U, raw text.
  - Minimal spoken support via TEI-CORPO TEI where straightforward.

- **Phase 2 – Spoken corpora**:
  - ELAN, TextGrid, Exmaralda, Transcriber, SRT.
  - TEI-CORPO TEI import/export.

- **Phase 3 – OCR/HTR and manuscripts**:
  - hOCR, PAGE XML (and TEITOK page structures).

- **Phase 4 – Annotation formats**:
  - brat, WebAnno, graphANNIS/SaltXML.

- **Phase 5 – Advanced back-ends**:
  - KonText/Manatee, TXM, Lexico, IRAMUTEQ, and other specialized exports.

At each phase, the mapping should be validated with **round-trip tests**:

- Format → FPM → TEITOK → FPM → Format (where possible).
- Format → FPM → other formats in the same family (e.g. different spoken formats).

