# Citation round-trip check — about 5 minutes in Word

You are testing whether the citations in a small test document survive
ordinary editing. You need **Microsoft Word** (Windows or macOS) and the file
**`spike_v1.docx`**. The document contains two short sentences of ordinary
text, two boxed **[1]** citations, and a short reference list.

Do the steps **in order**. Save whenever a step says so. When you finish,
send back **every file** you produced (there will be three).

A "boxed" citation is the citation text with a light box around it that Word
draws when you click inside it.

1. **Open and reopen.** Open `spike_v1.docx` in Word. Change nothing.
   Save it (Ctrl+S / Cmd+S). Close Word. Reopen the file.
   *(This checks the file survives an ordinary open/save cycle.)*

2. **Type some prose.** Click at the end of the **first** sentence of plain
   text — not inside a boxed [1] — and type one short extra sentence.
   Save.
   *(This checks the citations tolerate ordinary writing around them.)*

3. **Copy within this document.** Click on a boxed **[1]**, copy it
   (Ctrl+C / Cmd+C), click at the end of the other paragraph of plain text,
   and paste it (Ctrl+V / Cmd+V). Save.
   *(This checks a citation still works after being copied within the
   document.)*

4. **Copy into a new document.** Create a **brand-new blank document**.
   Copy a boxed **[1]** from `spike_v1.docx` and paste it into the new
   document. Save the new document as **`pasted.docx`**.
   *(This checks what a citation becomes in a document of its own.)*

5. **Edit with Track Changes on.** Turn on **Review → Track Changes**.
   In a paragraph containing a boxed **[1]**, click right next to it and
   type a few words. Save. Leave the tracked changes in place — do **not**
   accept or reject them.
   *(This checks citations survive edits made under Track Changes.)*

6. **Save a copy under a new name.** With `spike_v1.docx` open, use
   **File → Save As** and save a copy as **`spike_renamed.docx`**
   (format: Word Document, .docx).
   *(This checks the structures survive a save-as.)*

**Send back these three files:**

- `spike_v1.docx` (edited in steps 1–3 and 5)
- `pasted.docx` (from step 4)
- `spike_renamed.docx` (from step 6)

If anything looks broken on screen at any step — a citation that shows
strange text, an error, a missing reference list — make a note of what you
saw and send the note along with the files.
