# Vision preset

Settings for chats about images: screenshots, photos, documents, diagrams. The aim is that the same question about the same image gets the same answer.

## What goes wrong by default

Chat-oriented sampling (temperature 1.0 with a presence penalty of 1.5) works against image questions. On a test with two illustrations, asked the same thing four times each, a 35B Qwen model with those settings:

- described the same piece of clothing as a sleeveless hooded top, a hooded sweatshirt, a cropped jacket or vest, and a short-sleeved shirt;
- named a colour for footwear that is not in the picture, in half of the answers;
- once said the character resembled a well-known game mascot, which nothing in the image supports.

Reading clear text and counting clear shapes were not affected: transcribing an invoice and counting objects came out right every time under every setting. The trouble is confined to details that are small or ambiguous, where a high temperature picks a different guess each time and the presence penalty pushes toward words not used yet.

## What fixes it

Measured on the same test, word overlap between repeated answers to short questions (1.0 = identical):

| Setting | Clothing question | Colour question |
|---|---|---|
| temperature 1.0, presence penalty 1.5 | 0.35 - 0.49 | 0.55 - 0.56 |
| temperature 0.2, presence penalty 0 | 0.53 - 0.73 | 0.44 - 0.81 |
| the same, plus the "only what is clearly visible" rule | 0.74 - 0.87 | 0.77 - 0.81 |

With the rule the model also stopped inventing the footwear and answered "unclear" instead. Temperature 0.6 with the rule landed in between.

## Setup

Install the [Steady Vision](../functions/steady_vision.py) filter and enable it for the vision models, or globally. It applies exactly the third row, only while an image is among the recent messages, and leaves text chats on the model's normal settings. Nothing needs to change in the model itself.

To apply it by hand instead, set on the model: temperature `0.2`, presence penalty `0`, and add this to the system prompt:

```
When looking at an image, report only what is clearly visible. If a detail is small, hidden or unclear, say it is unclear instead of guessing. Copy text exactly as written. Do not name people, characters or brands unless readable text in the image names them.
```

## Which models need it

The problem showed on the Qwen model with chat settings. A 26B Gemma model at temperature 0.6 without a presence penalty was already consistent on the same kind of question (word overlap 0.70 - 0.77 before, 0.54 - 1.0 with the filter, three runs each, so within noise). The filter does no harm there but is not needed.

## Things to know

- Parameters set under Advanced Params of a model in Open WebUI win over the filter. If temperature or presence penalty is set there, clear it or the filter cannot change it. Values from an Ollama Modelfile are overridden as intended.
- Without the presence penalty the model thinks longer before a short answer about an image (about three times as much reasoning text in the test), and in 2 of 96 calls it used up a 3500-token limit while thinking and returned nothing. If answers come back empty or slow, set the filter's `presence_penalty` valve to `0.5`, or use the Quick Answer switch to skip thinking for simple image questions. The value 0.5 was not measured.
- With thinking off, descriptions were faster but no more consistent.
- For identical answers on a repeat, set the filter's `seed` valve to any number. Regenerate then gives the same answer again.
- Keep the image large enough to read. Open WebUI's image compression setting (Settings → Interface) shrinks uploads; small text in a screenshot is the first thing lost.
