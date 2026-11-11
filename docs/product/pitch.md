# Pitch: Transcriber, a transcript you can read, check and summarise (11 Nov 2026)

**Decision (Bogdan, 11 Nov): parked.** The app's functions are fine for now. Not wanted:
- naming speakers;
- search inside a transcript;
- keeping the audio;
- summaries and action items.

The three looks from the design round (Document, Tinted blocks, Summary first) are on the
claude.ai artifact "Receipts and Transcriber Redesign" for when this comes back.

Step 2 (homelab `docs/product-process.md`). For Bogdan to approve, change or cut before any
design is final or code is written.

## The problem

- The result is one block of plain text (`[00:01:12] Speaker A: ...`) in a monospace box. Long
  meetings are hard to read and impossible to search.
- **Speakers can't be named.** Every transcript says Speaker A and Speaker B.
- **There is no way to check a passage by ear.** The audio file is deleted when the job ends
  (`app.py`, `os.unlink(file_path)`), the same thing Granola users complain about most
  (`research.md`).
- **No summary or action items,** although the local Qwen 3.8 model runs on the same server and
  can do that privately. Work recordings may be used locally (`CLAUDE.md`, section 4).

## What we build

1. **A readable transcript.**
   - Paragraphs per speaker, each speaker with a name and a colour, and the time in the margin.
   - Rename a speaker once ("Speaker A" to "Ana") and it changes everywhere, saved with the job.
   - Search inside the transcript, with matches highlighted.
2. **Playback.**
   - Keep the audio for 30 days (a setting; 0 keeps nothing, as today).
   - A player bar at the bottom; tapping a paragraph plays from its start; the paragraph being
     played is highlighted.
   - Paragraph level is enough to start, because whisper gives start times per segment. Word
     level comes later, if wanted.
3. **Summary and action items from the local model,** on request ("Summarise"), never sent
   outside the house.
   - **Linked:** each summary line and action item carries its timestamp and jumps there.
   - **Marked:** AI text is shown in a softer colour with "AI" beside it until you edit or tick
     it.
   - **Tested first:** a test set of 5 real recordings with hand-written key points, before it is
     switched on (app contract, rule 11).
4. **Recordings as a library.** The jobs list becomes "Recordings", with titles you can edit,
   date, length, speakers, and search across all transcripts.

## Out of scope

- Live recording during a meeting.
- A bot joining calls.
- Word-level editing of the text.
- Chat across meetings: later, through Jarvis (`docs/jarvis-plan.md`).

## Time budget

About a week of sessions:
- one for the design round;
- two for the transcript, speakers and search;
- one for playback and keeping audio;
- one or two for summaries with their test set;
- one for QA.

## Risks

- **Kept audio is private data on disk.** It stays in `/data`, is deleted after the set number of
  days, and is covered by the backup when that is on. Encrypting the data disk is still an open
  question (`CLAUDE.md`).
- **The card is shared.** A summary of an hour-long meeting means about 15,000 tokens of input:
  roughly a minute to read and a minute or two to write on the 64K entry, while chats wait.
- **Speaker separation in mixed Romanian and English** may be weak (Otter's complaint). Renaming
  doesn't fix wrong splits; a "merge speakers" action does, and it is included.

## How we'll know it works

- Finding a sentence in an hour-long transcript takes under 15 seconds (search, tap, hear it).
- Speakers are named in under 30 seconds per meeting.
- On the test set, the summary's action items match the hand-written ones at least 4 times in 5,
  with none invented.
