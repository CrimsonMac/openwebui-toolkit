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

## Thinking in circles

With the thinking phase on, an image question can go round and round: the model counts or judges a detail, doubts it, looks "once more", and reaches the same point a few paragraphs later. Measured on the 35B Qwen model with one cluttered picture and a question about a count and a small sign, 2500 tokens allowed per answer:

| Setting | Answers given | Six-word sequences in the thinking that repeat |
|---|---|---|
| thinking on, temperature 0.2, presence penalty 0 | 0 of 3 (all 2500 tokens spent thinking) | 17 - 43 % |
| thinking on, temperature 0.6, presence penalty 1.5 | 0 of 3 | 2 - 6 % |
| thinking off, temperature 0.2, presence penalty 0 | 2 of 2, in 2 and 9 seconds | - |

So the low temperature that makes answers consistent also makes a thinking phase repeat itself word for word, and gentler sampling only makes the circling less literal: the model still did not get to an answer. Switching thinking off for image questions is what works. A picture does not change on a second look, so there is little for a thinking phase to gain.

## Setup

Install the [Steady Vision](../functions/steady_vision.py) filter and enable it for the vision models, or globally. While an image is among the recent messages it switches thinking off and applies the third row of the first table; text chats stay on the model's normal settings. Nothing needs to change in the model itself.

**Check the model's Advanced Params.** If Think is switched on there (Workspace → Models → the model → Advanced Params), it wins over the filter and thinking stays on. Set it to Default. The filter shows a notice in the chat when it sees this, and then leaves temperature and presence penalty alone so that it at least does not make the circling worse.

To apply it by hand instead, set on the model: Think off, temperature `0.2`, presence penalty `0`, and add this to the system prompt:

```
When looking at an image, report only what is clearly visible. If a detail is small, hidden or unclear, say it is unclear instead of guessing. Copy text exactly as written. Do not name people, characters or brands unless readable text in the image names them.
```

## Which models need it

The problem showed on the Qwen model with chat settings. A 26B Gemma model at temperature 0.6 without a presence penalty was already consistent on the same kind of question (word overlap 0.70 - 0.77 before, 0.54 - 1.0 with the filter, three runs each, so within noise). The filter does no harm there but is not needed.

## Things to know

- Parameters set under Advanced Params of a model in Open WebUI win over the filter. If temperature or presence penalty is set there, clear it or the filter cannot change it. Values from an Ollama Modelfile are overridden as intended.
- To keep thinking for image questions anyway, set the filter's `thinking` valve to `leave`. The filter then only adds the rules and keeps the chat's own temperature and presence penalty. Expect slow answers and, on pictures with many small details, sometimes none.
- With thinking off, descriptions were faster but no more consistent; the consistency comes from the sampling settings and the rule.
- The thinking test used one picture and one question on one model. The Gemma model was not tested for it.
- For identical answers on a repeat, set the filter's `seed` valve to any number. Regenerate then gives the same answer again.
- Keep the image large enough to read. Open WebUI's image compression setting (Settings → Interface) shrinks uploads; small text in a screenshot is the first thing lost.
