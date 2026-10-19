# Kapittelfiler

Egne kapittelfiler for cd SPILL. De går foran Podbeans egne, fordi Podbean fjerner skjulte
kapitler (`toc: false`) og lenker, og runder av tidskodene.

**Filnavnet må være det samme som i Podbeans `<podcast:chapters url="…">`,** f.eks.
`Outrun_chapters.json`. Lag fila med `chapters/export_chapters.py` i `../cdspill-produksjon`,
eller eksporter «Podcast Namespace JSON (without images)» fra
[mp3chapters.github.io](https://mp3chapters.github.io).

```json
{
  "version": "1.2.0",
  "chapters": [
    {"startTime": 0, "title": "Intro"},
    {"startTime": 1944.116, "title": "Ulike endings", "url": "https://www.vgmuseum.com/end/arcade/c/out.htm"},
    {"startTime": 2024.502, "title": "Vineyard", "toc": false},
    {"startTime": 2100, "title": "Star Wars: Rebel Assault II", "img": null}
  ]
}
```

- `toc: false`: med i MP3-en og JSON-en, men ikke i innholdslista (`psc:chapters`, YouTube).
- `url`: lenke. Peker den til Steam, GOG eller Wikipedia, får kapittelet spillets cover.
- `img`: utelat det, så velges bilde automatisk etter reglene i [`../podcast.toml`](../podcast.toml).
  `"img": null` slår det av når den automatiske matchingen bommer.

Berikingen sorterer kapitlene, legger til «Intro» ved 00:00 hvis det mangler, setter inn
bilder og lenker, og publiserer fila under `chapters/` på GitHub Pages. Den advarer når
antallet kapitler avviker fra Podbeans, og når en fil her ikke matcher noen episode.
