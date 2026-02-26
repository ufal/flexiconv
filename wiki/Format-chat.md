# CHAT / CLAN (`chat`)

## Tool and format

- **Tool**: [CLAN](https://talkbank.org/clan/) (Computerized Language Analysis) and [CHILDES](https://childes.talkbank.org/) (Child Language Data Exchange System), TalkBank.
- **Full format name**: CHAT (Codes for the Human Analysis of Transcripts); plain-text with tier lines and headers.
- **Format specification**: [CHAT manual](https://talkbank.org/manuals/CHAT.pdf) and [TalkBank CHAT](https://talkbank.org/support/chattranscription.html); file extension `.cha`.

## Origin and purpose

- **Origin**: CHAT (Codes for the Human Analysis of Transcripts) and CLAN (Computerized Language Analysis), used in CHILDES and other spoken corpora. `.cha` files are plain-text with tier lines and metadata headers.
- **Role in Flexiconv**: import CHAT transcripts into TEITOK-style TEI with `<u>` for speaker turns and `<note>` or inline elements for CHAT-specific tiers (e.g. %mor, %gra).

Handled by `flexiconv/io/chat.py`.

## Minimal example (conceptual)

CHAT files use lines like `*CHI: hello world .` and `%mor: ...`. Flexiconv maps main tiers to TEI `<u>` and preserves or maps dependent tiers where applicable.

## Conversion semantics

- **Reading (`chat` input)**:
  - Speaker tiers (`*XXX:`) → `<u>` with `@who`; text is tokenised into `<tok>`.
  - Metadata headers (e.g. `@Participants`) can be reflected in the TEI header or document meta.
  - Dependent tiers (`%mor`, `%gra`, etc.) are mapped to attributes or stand-off where supported.

- **Writing (`chat` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
