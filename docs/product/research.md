# Research: meeting transcript apps (11 Nov 2026)

Step 1 of the redesign (homelab `docs/product-process.md`). Report only; the decisions are in
`pitch.md`.

**How it was gathered.** The cloud session couldn't open several sites, so every claim comes from
web search results (summaries and snippets), not pages read in full. Where a summary mixed
sources, the URL is the closest match. Many sources are competitors' blogs or review aggregators.
No screenshots were seen, so the visual notes come from written descriptions.

## Otter.ai

- **Core loop:** a bot joins the call, or you record on the phone; afterwards you read the
  summary, then the transcript, and highlight and share
  ([Upwork](https://www.upwork.com/resources/how-otter-ai-works)).
- **Top features, all missing from our app:**
  - the current word highlighted during playback, and tapping a word jumps there;
  - name a speaker once and the name applies throughout;
  - search;
  - a summary with action items;
  - chat answers with speakers and timestamps
    ([App Store](https://apps.apple.com/us/app/otter-ai-voice-notes/id1276437113),
    [Otter blog](https://otter.ai/blog/ai-to-summarize-transcripts)).
- **Users say:**
  - the bot joining uninvited is resented ([eesel](https://www.eesel.ai/blog/otter-ai-reviews));
  - weak with many speakers (a competitor quoting Reddit,
    [circleback](https://circleback.ai/compare/fireflies-ai-vs-otter-ai));
  - "gibberish if you switch languages" ([tl;dv](https://tldv.io/blog/otter-ai-review/)), which
    matters for mixed Romanian and English.

## Fireflies.ai

- **Core loop:** a bot records; afterwards a "Notepad" holds the summary, transcript, recording,
  analytics and action items
  ([guide](https://guide.fireflies.ai/articles/6653885315-learn-about-the-fireflies-notepad)).
- **Top features:**
  - smart search filters for questions and tasks;
  - topic trackers;
  - action items;
  - talk time per speaker;
  - bookmarks and comments.
- **Users say:**
  - accuracy is the top praise ([G2](https://g2.com/products/fireflies-ai/reviews?page=2));
  - action items sometimes have the wrong owner or come from casual remarks
    ([Lindy](https://www.lindy.ai/blog/fireflies-ai-review)).
- **Look:** two panels, with a collapsible left panel for search and filters.

## MacWhisper (local, Mac)

- **Core loop:** drop in a file, or record live; it transcribes locally; you correct, run an AI
  prompt and export
  ([iThinkDiff](https://www.ithinkdiff.com/macwhisper-15-2-adds-real-time-meeting-transcripts-and-support-for-up-to-8-speakers/)).
- **Top features:**
  - speakers renamed once;
  - segment editing, with search and replace for repeated mistakes;
  - playback synced to the text;
  - AI prompts with a choice of model;
  - search.
- **Transcript:** each segment's background is tinted in its speaker's colour, and keys 1, 2 and
  3 assign speakers
  ([help](https://macwhisper.helpscoutdocs.com/article/32-automatic-speaker-recognition-in-macwhisper)).
- **Users say:**
  - praised by a former Otter user
    ([MacSparky](https://www.macsparky.com/blog/2025/03/macwhisper-12-now-with-automatic-speaker-recognition/));
  - speaker recognition called weak against whisperx in one Reddit comment.

## Granola

- **Core loop:** no bot; it records the device's audio. You type rough notes, then "Enhance
  notes" merges them with the transcript; you can chat with the notes and run saved prompts
  ("recipes") ([Zapier](https://zapier.com/blog/granola-ai.md)).
- **Users say:**
  - the summaries are praised;
  - the top complaint is that the audio is deleted, so a passage can't be replayed to check it
    ([anarlog, a competitor](https://anarlog.so/blog/granola-ai-complaints/)).
- **AI text looks different:** your words are black and the AI's additions grey; editing a grey
  line turns it black ([Granola](https://www.granola.ai/blog/announcement)).
- **Links back to the source:** each note has a magnifying glass that opens its place in the
  transcript.
- **Look:** one notepad, deliberately minimalist.

## Descript, Voice Memos, Google Recorder, Hyprnote

- **Descript:**
  - a blue playhead in the text;
  - correct words without touching the audio;
  - a glossary for names it mishears;
  - speaker labels you can move
    ([help](https://help.descript.com/script-editing/speaker-labels.md)).
- **Apple Voice Memos:** search across recordings matches transcript text
  ([Apple](https://support.apple.com/en-mide/guide/ipad/ipad282bee5e/ipados)).
- **Google Recorder:**
  - speakers you can rename;
  - search that jumps to the time;
  - on-device summaries ([Google](https://support.google.com/pixelphone/answer/16269004)).
- **Hyprnote** (now Char/anarlog): open source and local, merges notes with the transcript using a
  local model. The closest match to a private setup like ours; its licence couldn't be confirmed.

## Patterns worth considering for a one-person, private app

- The current passage highlighted during playback, and tap to jump (Otter, Descript).
- Keep the audio, so a passage can be checked by ear (Granola's top complaint).
- Name a speaker once, with a colour tint per speaker (Otter, Google Recorder, MacWhisper).
- Each summary line links back to its place in the transcript (Granola, Otter).
- AI text looks different from your own until you edit it (Granola).
- Search and replace, or a name glossary, for words it keeps getting wrong (MacWhisper,
  Descript). Useful for Romanian names.
- Saved prompts or templates for summaries (Granola, MacWhisper).
- Search inside one transcript and across all of them (Fireflies, Voice Memos, Google Recorder).
