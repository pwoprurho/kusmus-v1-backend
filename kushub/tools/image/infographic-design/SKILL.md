---
name: infographic-design
description: "Generate professional infographics, data visualizations, and educational diagrams using FLUX and DALL-E models via inference.sh CLI. Capabilities: layout planning, text-integrated diagrams, technical illustrations, and business charts. Triggers: infographic, diagram, chart, data viz, educational graphic, technical illustration"
allowed-tools: Bash(infsh *)
---

# Infographic & Data Visualization Design

Transform complex data into stunning visual narratives with the Infographic Design skill. Powered by Black Forest Labs (FLUX) and OpenAI (DALL-E 3) via the [inference.sh](https://inference.sh) CLI.

## Quick Start

```bash
infsh app run falai/flux-pro --input '{
  "prompt": "an infographic about solar energy efficiency, flat vector style, professional layout, labeled parts"
}'
```

## Supported Visual Styles

| Style | Description | Best For |
|-------|-------------|----------|
| **Flat Vector** | Minimalist, clean lines, and solid colors. | Modern business reports |
| **Technical Blueprint** | Schematic-like diagrams with detailed annotations. | Engineering and hardware specs |
| **Isometric 3D** | High-depth visuals showing spatial relationships. | Architecture and process flows |
| **Hand-Drawn Sketch** | Organic, human-centric feel for concepts. | Creative brainstorming |

## Advanced Examples

### Process Flow Diagram
```bash
infsh app run openai/dall-e-3 --input '{
  "prompt": "A step-by-step diagram of a water filtration system, 4 clear stages, labeled, white background"
}'
```

### Statistical Poster
```bash
infsh app run falai/flux-dev --input '{
  "prompt": "Infographic poster about global population growth, using icons instead of bars, high contrast, 4k"
}'
```

## Tips for Better Infographics
1. **Be Specific about Layout**: Mention "4 quadrants", "circular flow", or "vertical timeline".
2. **Define Text Requirements**: Specify "minimal text" or "placeholder labels" as AI text generation is improving but works best with limited characters.
3. **Set the Palette**: Define brand colors (e.g., "Deep blue and gold accent").

## Documentation
- [Inference.sh Docs](https://inference.sh/docs)
- [FLUX Prompting Guide](https://blackforestlabs.ai/prompting)
