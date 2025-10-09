# Spotify Album Art Generator - Dual AI Model Edition

> **Automated workflow for AI-powered album artwork generation using Spotify references, Google Sheets, and dual AI models**

## 📋 Overview

This workflow automates the process of generating AI-edited album artwork variations. It reads Spotify URLs and editing instructions from a Google Sheet, fetches the album artwork, and generates **4 different AI-edited variations** using two state-of-the-art models (Seedream-4 and Nano-Banana) with both original and AI-enhanced prompts.

**Perfect for**: Musicians, designers, and content creators who need to compare AI model outputs and generate multiple artwork variations efficiently.

## 🎯 What Problem Does This Solve?

**Before**: Manually downloading album covers, trying different AI tools, comparing results, managing multiple prompts, saving with proper organization.

**After**: One command processes your sheet—fetches artwork, generates 4 AI variations (2 models × 2 prompt styles), saves organized files with descriptive names, and documents the enhanced prompt.

**Key Benefits**:
- 🎨 **Model Comparison**: See Seedream-4 vs Nano-Banana side-by-side
- 🤖 **AI Prompt Enhancement**: Gemini 2.5 Pro automatically improves your prompts
- 🗂️ **Smart Organization**: Descriptive filenames (`{id}-{model}-{style}.jpg`)
- 📝 **Documentation**: Enhanced prompts saved as markdown
- 🚫 **Text Removal**: Automatically removes text/logos from all outputs

## 📖 What Happens During Execution

When you execute this workflow, it orchestrates a sophisticated multi-step process that transforms a simple instruction into four distinct AI-generated artwork variations. The journey begins the moment you run the command with your Google Sheet ID and Replicate API token. Behind the scenes, the workflow immediately connects to your Google Sheet and retrieves all data from columns A through H in a single efficient API call. This raw spreadsheet data flows into the system as a JSON structure, ready to be parsed and processed.

The workflow then intelligently searches through your sheet data, filtering through all the rows to identify entries that contain valid Spotify URLs in column G. It doesn't just grab the first match—it specifically targets the last row with a Spotify URL, which allows you to easily add new entries to the bottom of your sheet and have them processed automatically. From this identified row, three critical pieces of information are extracted: the filename from column A (which will become the base name for all generated files), the Spotify URL from column G (which points to the track or album artwork), and your creative instruction from column H (which tells the AI models what edits to make).

With the Spotify URL in hand, the workflow reaches out to Spotify's public oEmbed API—a free service that doesn't require authentication. This API call returns rich metadata about the track or album, including most importantly the thumbnail_url property, which points directly to the official album artwork hosted on Spotify's CDN. This thumbnail image, typically 300×300 pixels in size, becomes the foundational input for all subsequent AI transformations.

Now comes the first major creative phase: generating the original prompt variations. The workflow takes your instruction from the sheet and automatically appends a crucial directive: "Remove all text, logos, and typography from the image." This ensures that all generated artwork will be clean, professional, and free from any unwanted text elements. This enhanced instruction, combined with the Spotify thumbnail URL, is then sent simultaneously to two different AI models. First, Seedream-4 by ByteDance receives the request—this model specializes in precise image editing and object replacement, and it generates a high-resolution 2048×2048 pixel (2K) result after about 10-13 seconds of processing. In parallel, the same prompt and thumbnail are sent to Nano-Banana, Google's Gemini-based image editing model, which approaches the task with its own interpretation, typically completing in 7-9 seconds with results that emphasize natural color blending and artistic harmony. Both resulting images are downloaded and saved to your local `generated-images/` directory with descriptive filenames that include the ID from your sheet, the model name, and the "original" designation.

But the workflow doesn't stop at these initial variations. Next, it enters an intelligent enhancement phase powered by Gemini 2.5 Pro, Google's most advanced language model. This LLM receives both the Spotify thumbnail and your original instruction, and it performs a sophisticated analysis. Gemini examines the visual elements of the artwork, understands your creative intent, and then crafts an extensively detailed, technically precise prompt that expands your simple instruction into a comprehensive art direction document. Where you might have written "replace the snake with a red cat," Gemini transforms this into a paragraph-long directive that specifies exact color values ("deep, saturated crimson hue"), lighting techniques ("high-contrast, low-key studio lighting with strong specular highlights"), texture details ("finely detailed fur capturing texture and sheen"), and professional output requirements. Crucially, Gemini is also instructed to use only content-safe, technical language to avoid triggering content moderation systems—it knows to avoid suggestive or provocative terms and instead employs neutral, professional terminology appropriate for commercial artwork. This enhanced prompt is immediately saved to a markdown file in your generated-images directory, creating a permanent record of both your original instruction and Gemini's professional enhancement.

Armed with this AI-enhanced prompt, the workflow now generates the second set of variations. The enhanced prompt—now rich with technical art direction, lighting specifications, and compositional details—is sent back to both Seedream-4 and Nano-Banana along with the same Spotify thumbnail. These models now have significantly more context and guidance, allowing them to produce results with greater precision and professional polish. Seedream-4 takes about 15-20 seconds to generate its enhanced version, while Nano-Banana completes its interpretation in roughly 7-10 seconds. Both images are downloaded and saved with filenames indicating they were generated with the "enhanced" prompt style.

Throughout this entire process, spanning approximately 60-70 seconds from start to finish, the workflow maintains a clean, organized output structure. Every file follows a consistent naming convention that makes it immediately clear which model generated it and whether it used your original instruction or the AI-enhanced version. When the workflow completes, you're left with five files in your generated-images directory: four JPG images representing different combinations of models and prompt styles, and one markdown file that documents the prompt enhancement journey. You can now compare how Seedream-4 and Nano-Banana interpreted the same instruction differently, evaluate whether the AI-enhanced prompts produced better results than your original instruction, and choose the best variation for your needs—or use all four for different purposes.

## 🚀 Quick Start

```bash
uv run pflow spotify-art-generator sheet_id="YOUR_SHEET_ID" replicate_api_token="YOUR_REPLICATE_TOKEN"
```

**Result**: 4 images + 1 markdown file saved to `generated-images/`:
- `{filename}-seedream-original.jpg`
- `{filename}-nano-original.jpg`
- `{filename}-seedream-enhanced.jpg`
- `{filename}-nano-enhanced.jpg`
- `{filename}-enhanced-prompt.md`

## 📊 Google Sheet Structure

Your sheet needs **3 specific columns**:

| Column A | Column G | Column H |
|----------|----------|----------|
| **Filename** | **Spotify URL** | **Edit Instruction** |
| `track-001` | `https://open.spotify.com/track/...` | `replace the snake with a red cat` |
| `summer-vibes` | `https://open.spotify.com/track/...` | `add sunset colors in the background` |
| `remix-2024` | `https://open.spotify.com/track/...` | `change to neon pink and blue tones` |

**Important Details**:
- **Column A**: Used as the base filename (sanitized automatically)
- **Column G**: Must contain a valid Spotify track/album URL
- **Column H**: Natural language instruction for editing
- **Last row**: The workflow processes the **last row** that contains a Spotify URL

## 🔧 Prerequisites

### 1. Google Sheets Access
- Sheet must be accessible via Composio's Google Sheets MCP
- Ensure MCP server is running and authenticated

### 2. Replicate API Token
Get your token from: https://replicate.com/account/api-tokens

**Free tier**: $5 credit (~70 runs / 280 images)
**Cost per run**: ~$0.06-0.07 USD (4 images)

### 3. Spotify URLs
Any valid Spotify URL format works:
- Tracks: `https://open.spotify.com/track/TRACK_ID`
- Albums: `https://open.spotify.com/album/ALBUM_ID`

## 📖 How It Works

### Step-by-Step Process:

**1. Fetch Sheet Data** (columns A through H)
   - Single API call to Google Sheets
   - Efficient data retrieval

**2. Extract Row Information**
   - Finds the last row with a Spotify URL in column G
   - Extracts 3 values:
     - Column A → Filename
     - Column G → Spotify URL
     - Column H → Edit instruction

**3. Get Album Artwork**
   - Calls Spotify oEmbed API
   - Retrieves official album artwork thumbnail (300×300px)

**4. Generate Original Variations** (2 images)
   - **Seedream-4**: ByteDance's image editing model (2K resolution)
   - **Nano-Banana**: Google's Gemini-based model (matched resolution)
   - Both use: Original prompt + text removal instruction
   - Saves: `{filename}-seedream-original.jpg` and `{filename}-nano-original.jpg`

**5. AI Prompt Enhancement**
   - **Gemini 2.5 Pro** analyzes the thumbnail + original prompt
   - Adds technical details (lighting, composition, color theory)
   - Ensures content-safe language (avoids moderation flags)
   - Emphasizes text/logo removal
   - Saves enhanced prompt to markdown file

**6. Generate Enhanced Variations** (2 images)
   - **Seedream-4**: Uses AI-enhanced prompt
   - **Nano-Banana**: Uses AI-enhanced prompt
   - Saves: `{filename}-seedream-enhanced.jpg` and `{filename}-nano-enhanced.jpg`

**7. Documentation**
   - Creates markdown file: `{filename}-enhanced-prompt.md`
   - Contains original prompt + AI-enhanced version
   - Useful for comparing prompt strategies

### Execution Time: ~60-70 seconds

**Breakdown**:
- Sheet fetch: ~3-5s
- oEmbed API: ~0.2s
- Seedream-4 (original): ~10-13s
- Nano-Banana (original): ~7-9s
- Gemini prompt enhancement: ~14-17s
- Seedream-4 (enhanced): ~15-20s
- Nano-Banana (enhanced): ~7-10s
- Downloads + file I/O: ~2-3s

## 💡 Usage Examples

### Basic Usage
```bash
uv run pflow spotify-art-generator \
  sheet_id="1vON91vaoXqf4ITjHJd_yyMLLNK0R4FXVSfzGsi1o9_Y" \
  replicate_api_token="r8_xxxxx"
```

### With Environment Variable
```bash
# Set once
export REPLICATE_API_TOKEN="r8_xxxxx"

# Then use in workflow
uv run pflow spotify-art-generator \
  sheet_id="YOUR_SHEET_ID" \
  replicate_api_token="$REPLICATE_API_TOKEN"
```

### Batch Processing Multiple Sheets
```bash
# Process different sheets with same token
for sheet in "sheet1" "sheet2" "sheet3"; do
  uv run pflow spotify-art-generator \
    sheet_id="$sheet" \
    replicate_api_token="$REPLICATE_API_TOKEN"
done
```

## 📤 Workflow Outputs

The workflow returns **8 outputs**:

```json
{
  "seedream_original_file": "generated-images/0021-seedream-original.jpg",
  "nano_original_file": "generated-images/0021-nano-original.jpg",
  "seedream_enhanced_file": "generated-images/0021-seedream-enhanced.jpg",
  "nano_enhanced_file": "generated-images/0021-nano-enhanced.jpg",
  "filename_from_sheet": "0021",
  "original_prompt": "Replace the snake with a red cat.\n",
  "enhanced_prompt": "In the central negative space...",
  "enhanced_prompt_file": "generated-images/0021-enhanced-prompt.md"
}
```

**Output Details**:
- **seedream_original_file**: Seedream-4 with original prompt
- **nano_original_file**: Nano-Banana with original prompt
- **seedream_enhanced_file**: Seedream-4 with AI-enhanced prompt
- **nano_enhanced_file**: Nano-Banana with AI-enhanced prompt
- **filename_from_sheet**: Original name from column A
- **original_prompt**: Your instruction from column H
- **enhanced_prompt**: Gemini's improved version with technical details
- **enhanced_prompt_file**: Path to markdown documentation file

## 🎨 Prompt Writing Tips

Both models work best with clear, specific instructions:

### ✅ Good Prompts:
- `"replace the cat with a dog"`
- `"add fireworks in the background"`
- `"change colors to neon pink and blue"`
- `"remove the text from the image"`
- `"transform to watercolor style"`

### ❌ Less Effective Prompts:
- `"make it better"` (too vague)
- `"add more vibes"` (unclear instruction)
- `"be creative"` (AI needs direction)

### Best Practices:
1. **Be specific**: Mention what to change and how
2. **Use reference objects**: "Replace X with Y" works well
3. **Style transformations**: "Transform to [style]" is effective
4. **Trust AI enhancement**: Gemini will add technical details

## 🤖 AI Prompt Enhancement

### What Gemini 2.5 Pro Adds:

**Your original**: `"Replace the snake with a red cat"`

**Gemini enhances to**:
```
In the central negative space of the open mouth, replace the serpentine
figure with a small, hyperrealistic red cat. The cat should be rendered
in a deep, saturated crimson hue that complements the color palette.
Its fur should be finely detailed, capturing texture and sheen under
dramatic lighting. Maintain high-contrast, low-key studio lighting
with strong specular highlights. Completely remove all text, artist
names, and typography.
```

**Enhancement benefits**:
- ✅ Adds technical art direction (lighting, composition, color theory)
- ✅ Specifies professional output quality
- ✅ Uses content-safe language (avoids moderation)
- ✅ Emphasizes text removal
- ✅ Maintains your creative intent

## 🔍 Model Comparison

### Seedream-4 (ByteDance)
- **Strengths**: Object replacement, style transfer
- **Resolution**: 2048×2048px (2K)
- **Speed**: ~10-20 seconds
- **Cost**: ~$0.03 per image
- **Best for**: Precise edits, object swaps

### Nano-Banana (Google Gemini)
- **Strengths**: Natural blending, color harmony
- **Resolution**: Matches input (300×300 from Spotify)
- **Speed**: ~7-10 seconds
- **Cost**: ~$0.03 per image
- **Best for**: Artistic transformations, style changes

**Why both?**: Different AI models interpret prompts differently. Having both lets you choose the best result or use both for A/B testing.

## 🗂️ File Organization

Generated files follow this convention:

```
generated-images/
├── {filename}-seedream-original.jpg    # Seedream-4 + original prompt
├── {filename}-nano-original.jpg        # Nano-Banana + original prompt
├── {filename}-seedream-enhanced.jpg    # Seedream-4 + AI-enhanced prompt
├── {filename}-nano-enhanced.jpg        # Nano-Banana + AI-enhanced prompt
└── {filename}-enhanced-prompt.md       # Prompt documentation
```

**Filename Pattern**: `{id}-{model}-{style}.jpg`
- **id**: From column A (sanitized)
- **model**: `seedream` or `nano`
- **style**: `original` or `enhanced`

**Benefits**:
- ✅ Self-documenting filenames
- ✅ Easy to find specific model outputs
- ✅ Clear original vs enhanced distinction
- ✅ Alphabetically sorted by ID

## 🛠️ Technical Details

### Workflow Architecture

**Nodes**: 15 nodes (streamlined with nested template access)

```
1. get-sheet-data              # Fetch Google Sheet
2. extract-filename            # Parse filename from column A
3. extract-spotify-url         # Extract Spotify URL from column G
4. extract-prompt              # Get instruction from column H
5. call-oembed                 # Get album artwork from Spotify
6. generate-image-seedream-original    # Seedream-4 (original prompt)
7. download-image-1            # Save seedream-original.jpg
8. generate-image-nano-original        # Nano-Banana (original prompt)
9. download-image-2            # Save nano-original.jpg
10. enhance-prompt             # Gemini 2.5 Pro enhancement
11. save-enhanced-prompt       # Save markdown file
12. generate-image-seedream-enhanced   # Seedream-4 (enhanced prompt)
13. download-image-3           # Save seedream-enhanced.jpg
14. generate-image-nano-enhanced       # Nano-Banana (enhanced prompt)
15. download-image-4           # Save nano-enhanced.jpg
```

**Key Technologies**:
- **Google Sheets API**: Via Composio MCP server
- **Spotify oEmbed API**: Public API, no auth required
- **Replicate API**: Seedream-4 + Nano-Banana models
- **Gemini API**: Via llm library (Simon Willison's CLI tool)
- **Nested Template Access**: Direct JSON property access (no jq extraction)
- **Shell + jq**: Data extraction from complex structures
- **curl**: Binary file download

### Nested Template Access Feature

The workflow uses pflow's nested template access to simplify data flow:

**Before** (old way):
```json
{
  "id": "extract-thumbnail",
  "type": "shell",
  "command": "jq -r '.thumbnail_url'"
}
// Then reference: ${extract-thumbnail.stdout}
```

**After** (nested access):
```json
// Direct reference: ${call-oembed.response.thumbnail_url}
```

**Benefits**:
- ✅ 25% fewer nodes (20 → 15)
- ✅ Cleaner workflow visualization
- ✅ Direct property access
- ✅ Less data copying between nodes

### Data Flow

```
Google Sheet (A:H)
  ↓
JQ parses → Finds last row with Spotify URL
  ↓
Extracts: [Column A, Column G, Column H]
  ↓
Column G → Spotify oEmbed → Thumbnail URL
  ↓
[Thumbnail + Column H] → Seedream-4 (original) → Image 1
  ↓
[Thumbnail + Column H] → Nano-Banana (original) → Image 2
  ↓
[Thumbnail + Column H] → Gemini 2.5 Pro → Enhanced Prompt → Markdown
  ↓
[Thumbnail + Enhanced Prompt] → Seedream-4 (enhanced) → Image 3
  ↓
[Thumbnail + Enhanced Prompt] → Nano-Banana (enhanced) → Image 4
```

### Filename Sanitization

Applied transformations:
1. Multiple spaces → Single hyphen: `"track  001"` → `"track-001"`
2. Special chars removed: `"track#001"` → `"track001"`
3. Only keeps: Letters, numbers, hyphens, underscores, dots

### Image Specifications

**Input** (from Spotify):
- Format: JPEG
- Size: 300×300px (thumbnail)
- Source: Spotify CDN

**Output** (Seedream-4):
- Format: JPEG
- Size: 2048×2048px (2K)
- Source: Replicate CDN

**Output** (Nano-Banana):
- Format: JPEG
- Size: Matches input aspect ratio
- Source: Replicate CDN

## 💰 Cost & Performance

### Replicate Costs (per run)
- **Seedream-4 (original)**: $0.03
- **Nano-Banana (original)**: $0.03
- **Seedream-4 (enhanced)**: $0.03
- **Nano-Banana (enhanced)**: $0.03
- **Total**: ~$0.12 per run (4 images)

### Gemini Costs (per run)
- **Gemini 2.5 Pro**: ~$0.014-0.016
- **Tokens**: ~500 input + ~1400 output

### Total Cost per Run
- **AI generation**: ~$0.134-0.136
- **Free tier**: $5 credit = ~35-37 runs = ~140-150 images

### Performance Metrics
- **Total execution**: 60-70 seconds
- **Sheets API**: ~3-5 seconds
- **Image generations**: ~40-50 seconds (4 images)
- **LLM enhancement**: ~14-17 seconds
- **Downloads + I/O**: ~2-3 seconds

### Rate Limits
- **Replicate**: 600 requests/minute
- **Gemini**: Depends on API tier
- **Spotify oEmbed**: No documented limit
- **Google Sheets**: Via MCP (depends on setup)

## 🚫 Text Removal Feature

All 4 generated images automatically remove text, logos, and typography from the source artwork.

**How it works**:
- Original prompts append: "Remove all text, logos, and typography from the image"
- Enhanced prompts include: "Completely remove all text, artist names, and typography"
- Both models apply text removal during generation

**Why this matters**:
- Clean artwork for creative projects
- Removes watermarks and labels
- Professional presentation
- Legal compliance (derivative works)

## ⚠️ Troubleshooting

### "Template variable not found"
**Problem**: Sheet structure doesn't match expected columns

**Solution**: Ensure you have data in columns A, G, and H

---

### "No Spotify URL found"
**Problem**: Column G doesn't contain a valid Spotify URL

**Solution**:
- Check column G has URLs starting with `https://open.spotify.com`
- Ensure at least one row has a Spotify URL

---

### "HTTP 401 Unauthorized" (Replicate)
**Problem**: Invalid or expired API token

**Solution**:
- Get a fresh token from https://replicate.com/account/api-tokens
- Check token has no extra spaces

---

### "Content flagged for: sexual"
**Problem**: Gemini generated a prompt that triggered content moderation

**Solution**:
- This is rare - the prompt engineering is designed to avoid this
- Try rephrasing your original instruction
- The workflow will fail at `generate-image-seedream-enhanced` or `generate-image-nano-enhanced`

---

### "Image generation timeout"
**Problem**: Model took longer than expected (>60 seconds)

**Solution**:
- Re-run the workflow
- Usually completes in 10-20 seconds per image

---

### "Gemini API error"
**Problem**: LLM enhancement failed

**Solution**:
- Ensure `llm` CLI tool is installed and configured
- Check Gemini API key: `llm keys set gemini`
- Verify model access: `llm models`

## 🎓 Advanced Usage

### Custom Output Directory
Modify download nodes to change output directory:

```bash
mkdir -p my-custom-dir && curl ... -o "my-custom-dir/$filename-{model}-{style}.jpg"
```

### Process Multiple Rows
Current workflow processes the **last row**. To process all rows:
- Modify jq to return array
- Use shell loop or workflow iteration
- *Note: Requires significant workflow modification*

### Different LLM Model
To use a different enhancement model, edit `enhance-prompt` node:
```json
{
  "model": "claude-sonnet-4.5"  // Change from "gemini-2.5-pro"
}
```
*Note: Claude has compatibility issues with usage metrics (known bug)*

### Skip Enhancement Step
To only generate original variations (2 images):
- Remove nodes: `enhance-prompt`, `save-enhanced-prompt`, `generate-image-*-enhanced`, `download-image-3`, `download-image-4`
- Update edges to end at `download-image-2`
- Reduces cost to ~$0.06 per run

## 📚 Related Resources

- **Seedream-4 Model**: https://replicate.com/bytedance/seedream-4
- **Nano-Banana Model**: https://replicate.com/google/nano-banana
- **Replicate Docs**: https://replicate.com/docs
- **Spotify oEmbed**: https://developer.spotify.com/documentation/embeds/references/oembed

