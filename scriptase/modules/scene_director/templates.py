"""Scene Style Templates — Pre-tuned visual style presets for AI scene generation.

Each template bundles a style_prompt (LLM instructions for generating image prompts)
along with display metadata for the frontend picker.

Templates with ``"category": True`` double as story-generation categories.
``STORY_CATEGORIES`` is derived automatically — keep this file as the single source.
"""

from scriptase.modules.scene_director.style_compiler import enrich_templates

SCENE_STYLE_TEMPLATES = [
    {
        "id": "cinematic",
        "type": "visual",
        "category": None,
        "name": "Cinematic Realistic",
        "description": "Photorealistic, dramatic lighting, film grain",
        "color": "#4ECDC4",
        "style_prompt": (
            "Generate photorealistic image prompts with cinematic composition. "
            "Use dramatic lighting (golden hour, chiaroscuro, volumetric light rays). "
            "Include film grain texture, shallow depth of field, and anamorphic lens flare. "
            "Frame shots like a Hollywood cinematographer — wide establishing shots, "
            "medium close-ups for emotion, extreme close-ups for tension. "
            "Color palette: rich, saturated, with teal-orange contrast."
        ),
    },
    {
        "id": "dark_horror",
        "type": "hybrid",
        "category": "horror",
        "name": "Dark / Horror",
        "description": "Eerie shadows, desaturated tones, unsettling atmosphere",
        "color": "#FF6B6B",
        "style_prompt": (
            "Generate dark, unsettling image prompts for horror storytelling. "
            "Use heavy shadows, low-key lighting, and desaturated cold tones (blue-grey, sickly green). "
            "Include fog, mist, silhouettes, and partially obscured subjects. "
            "Environments should feel abandoned, decaying, or claustrophobic. "
            "Faces should be partially hidden or lit from below. "
            "Atmosphere: dread, unease, isolation. Think atmospheric horror, not gore."
        ),
    },
    {
        "id": "reddit_story",
        "type": "hybrid",
        "category": "anecdote",
        "name": "Reddit Story",
        "description": "Everyday realism, relatable settings, subtle tension",
        "color": "#FF8A50",
        "style_prompt": (
            "Generate realistic, grounded image prompts for Reddit-style personal stories. "
            "Settings are everyday and relatable: apartments, offices, cars, restaurants, suburban homes. "
            "Lighting should feel natural — overhead fluorescents, laptop screen glow, afternoon window light. "
            "People should look like normal, non-glamorous individuals. "
            "Use medium shots and over-the-shoulder angles for conversational scenes. "
            "Mood shifts with the narrative: warm tones for happy moments, cool desaturated for conflict. "
            "Style: modern photorealistic, candid photography feel."
        ),
    },
    {
        "id": "motivational",
        "type": "hybrid",
        "category": "motivation",
        "name": "Motivational",
        "description": "Bright, uplifting, high-contrast inspirational visuals",
        "color": "#FFD93D",
        "style_prompt": (
            "Generate uplifting, inspirational image prompts with high visual energy. "
            "Use bright, warm lighting — sunrise/sunset, golden backlighting, lens flare. "
            "Include expansive landscapes, mountain peaks, open skies, and silhouettes against light. "
            "People should appear determined, triumphant, or in motion (running, climbing, reaching). "
            "Color palette: warm golds, deep blues, vibrant oranges. High contrast. "
            "Composition: epic wide shots, low-angle hero shots, dramatic scale."
        ),
    },
    {
        "id": "nature_doc",
        "type": "hybrid",
        "category": "nature",
        "name": "Nature Documentary",
        "description": "BBC Earth aesthetics, macro detail, sweeping landscapes",
        "color": "#26DE81",
        "style_prompt": (
            "Generate nature documentary-style image prompts with BBC Earth quality. "
            "Use extreme macro for small subjects (insects, dewdrops, textures) and "
            "sweeping aerial/wide shots for landscapes. "
            "Lighting: natural golden hour, dappled forest light, underwater caustics. "
            "Include wildlife in natural behavior, pristine environments, and ecological detail. "
            "Color palette: lush greens, ocean blues, earth tones. "
            "Composition: rule of thirds, leading lines in nature, shallow DOF on subjects."
        ),
    },
    {
        "id": "anime",
        "type": "visual",
        "category": None,
        "name": "Anime / Manga",
        "description": "Japanese animation style, vivid colors, expressive characters",
        "color": "#A78BFA",
        "style_prompt": (
            "Generate image prompts in Japanese anime/manga art style. "
            "Characters should have expressive faces with large eyes, dynamic poses, and stylized hair. "
            "Use vivid, saturated colors with cel-shading and clean line art. "
            "Backgrounds should be detailed and painterly (Makoto Shinkai sky style). "
            "Include speed lines for action, sparkle effects for emotion, "
            "and dramatic camera angles (dutch angles, extreme low/high). "
            "Lighting: rim lighting, dramatic backlighting, neon glows for night scenes."
        ),
    },
    {
        "id": "surreal",
        "type": "visual",
        "category": None,
        "name": "Surreal / Dreamlike",
        "description": "Impossible geometry, floating objects, otherworldly scenes",
        "color": "#E879F9",
        "style_prompt": (
            "Generate surreal, dreamlike image prompts with impossible or fantastical elements. "
            "Include floating objects, impossible architecture, melting landscapes, and scale distortions. "
            "Mix unexpected elements: clocks in forests, doors in oceans, stairs to nowhere. "
            "Use soft, diffused lighting with iridescent or bioluminescent accents. "
            "Color palette: pastels mixed with deep jewel tones, gradient skies. "
            "Composition: center-weighted with vast negative space. "
            "Style: between Salvador Dali and modern digital surrealism."
        ),
    },
    {
        "id": "noir",
        "type": "visual",
        "category": None,
        "name": "Noir / Mystery",
        "description": "High contrast B&W, venetian blinds, smoky atmosphere",
        "color": "#94A3B8",
        "style_prompt": (
            "Generate film noir-style image prompts with classic detective/mystery atmosphere. "
            "Use high-contrast black and white or very desaturated tones with a single accent color. "
            "Lighting: harsh venetian blind shadows, single-source desk lamps, neon reflections on wet streets. "
            "Include rain-slicked city streets, smoky interiors, long shadows, and trench coat silhouettes. "
            "Composition: dutch angles, deep shadows covering half the frame, mirror/reflection shots. "
            "Atmosphere: mysterious, morally ambiguous, tension without violence."
        ),
    },
    {
        "id": "minimal",
        "type": "visual",
        "category": None,
        "name": "Minimalist",
        "description": "Clean compositions, negative space, simple shapes",
        "color": "#6B7F93",
        "style_prompt": (
            "Generate minimalist image prompts with maximum visual impact from minimal elements. "
            "Use vast negative space, single focal subjects, and geometric simplicity. "
            "Color palette: monochromatic or limited to 2-3 colors. "
            "Composition: centered single subject, extreme negative space, "
            "clean horizons, isolated objects on plain backgrounds. "
            "Lighting: soft, even, shadowless OR single dramatic shadow. "
            "Style: modern design photography, architectural minimalism."
        ),
    },
    {
        "id": "minimal_illustration",
        "type": "visual",
        "category": None,
        "name": "Minimalist Illustration",
        "description": "Bold single object on vast white space, flat geometric style, origami-like forms",
        "color": "#E74C3C",
        "style_prompt": (
            "Generate minimalist illustration image prompts with a single bold focal object on vast empty white or light background. "
            "Style: flat illustration, geometric/origami-like forms, paper-craft aesthetic, clean vector lines. "
            "Composition: the subject occupies less than 30% of the frame, surrounded by enormous negative space. "
            "Use portrait/vertical 9:16 framing. The subject should feel isolated, contemplative, floating in space. "
            "Color: one bold accent color (red, teal, gold, deep blue) against pure white or very light background. "
            "No textures, no gradients on background — keep it surgically clean. "
            "Subjects: simple symbolic objects (paper airplane, origami boat, lone figure, single tree, floating cube, "
            "envelope, key, umbrella, lightbulb, compass). Each scene uses ONE object as a visual metaphor. "
            "Lighting: soft, even, almost shadowless — the object creates its own visual weight through color contrast alone. "
            "Mood: contemplative, poetic, spacious, breathing room. Think editorial illustration meets zen philosophy. "
            "Camera angles vary per scene type: "
            "- Establishing: extreme wide, subject tiny in center "
            "- Close-up: subject fills 50% but still generous margins "
            "- Over-shoulder: silhouette of observer looking at distant object "
            "- Bird's-eye: top-down geometric pattern with subject as focal point "
            "- Medium: centered subject with balanced negative space on all sides"
        ),
    },
    {
        "id": "cyberpunk",
        "type": "visual",
        "category": None,
        "name": "Cyberpunk / Neon",
        "description": "Neon-soaked streets, futuristic tech, rain-slicked chrome",
        "color": "#00FFF7",
        "style_prompt": (
            "Generate cyberpunk-style image prompts with a neon-drenched futuristic aesthetic. "
            "Use vibrant neon lighting in magenta, cyan, and electric blue against dark environments. "
            "Include rain-slicked streets reflecting holographic advertisements, towering megastructures, "
            "augmented humans, and gritty back-alleys filled with steam and wires. "
            "Color palette: deep blacks with saturated neon accents — pink, teal, purple. "
            "Lighting: neon signage, holographic projections, LED strips, underlighting. "
            "Composition: low-angle shots emphasizing scale, tight alleys with depth, Dutch angles."
        ),
    },
    {
        "id": "vintage_retro",
        "type": "visual",
        "category": None,
        "name": "Vintage / Retro",
        "description": "70s-80s film stock, warm faded tones, analog nostalgia",
        "color": "#D4A574",
        "style_prompt": (
            "Generate image prompts with a warm vintage aesthetic reminiscent of 1970s-1980s film photography. "
            "Use faded, warm color tones — amber, burnt orange, olive green, mustard yellow. "
            "Include film grain, slight overexposure, light leaks, and soft focus edges. "
            "Settings should feel nostalgic: wood-paneled rooms, analog TVs, station wagons, diners. "
            "Lighting: warm tungsten, late afternoon sun through curtains, golden hour haze. "
            "Composition: slightly off-center, casual framing as if from a family photo album. "
            "Style: Kodachrome and Polaroid aesthetics, analog warmth."
        ),
    },
    {
        "id": "fantasy_epic",
        "type": "visual",
        "category": None,
        "name": "Fantasy / Epic",
        "description": "Mythical worlds, dragons, castles, enchanted landscapes",
        "color": "#C084FC",
        "style_prompt": (
            "Generate epic fantasy-style image prompts with grand, mythical world-building. "
            "Include towering castles, enchanted forests, dragons, ancient ruins, and magical creatures. "
            "Use dramatic, painterly lighting — god rays through storm clouds, aurora borealis, fire glow. "
            "Environments should feel vast and awe-inspiring with extreme scale. "
            "Color palette: deep purples, emerald greens, molten golds, sapphire blues. "
            "Composition: sweeping panoramic establishing shots, hero silhouettes against epic backdrops. "
            "Style: high fantasy digital painting, concept art quality, Tolkien-inspired grandeur."
        ),
    },
    {
        "id": "sci_fi",
        "type": "visual",
        "category": None,
        "name": "Sci-Fi / Space",
        "description": "Spaceships, alien worlds, futuristic technology, cosmic scale",
        "color": "#38BDF8",
        "style_prompt": (
            "Generate science fiction image prompts with futuristic and cosmic imagery. "
            "Include sleek spacecraft, alien planets, space stations, wormholes, and advanced technology. "
            "Use clean, cool lighting — blue-white ship interiors, starfield illumination, planetary glow. "
            "Environments: vast space vistas, sterile corridors, terraformed landscapes, zero-gravity scenes. "
            "Color palette: steel blues, deep space blacks, white LED accents, holographic teal. "
            "Composition: extreme wide shots for scale, symmetrical interiors, lens flare from distant stars. "
            "Style: hard sci-fi realism, NASA meets Hollywood — Interstellar, The Expanse, Blade Runner 2049."
        ),
    },
    {
        "id": "watercolor",
        "type": "visual",
        "category": None,
        "name": "Watercolor / Painted",
        "description": "Soft washes, visible brushstrokes, artistic illustration",
        "color": "#FB923C",
        "style_prompt": (
            "Generate image prompts in a watercolor painting style with artistic, handmade quality. "
            "Use soft color washes that bleed into each other, visible brushstrokes, and wet-on-wet effects. "
            "Leave areas of white paper showing through for highlights and breathing room. "
            "Colors should be luminous and translucent — not opaque or flat. "
            "Include gentle gradients, organic edges, and slightly imprecise details that feel hand-painted. "
            "Subjects should feel delicate and atmospheric rather than photorealistic. "
            "Style: traditional watercolor illustration, children's book art, botanical painting."
        ),
    },
    {
        "id": "bold_cartoon",
        "type": "visual",
        "category": None,
        "name": "Bold Cartoon",
        "description": "Thick black outlines, flat vibrant colors, dynamic energy lines, solid backgrounds",
        "color": "#FBBF24",
        "style_prompt": (
            "Generate image prompts in bold cartoon illustration style with thick black outlines and flat vibrant colors. "
            "Subjects should be stylized and slightly exaggerated — expressive hands, confident poses, iconic gestures. "
            "Use simple solid-color backgrounds (bright yellow, electric blue, hot pink, vivid orange) with NO complex scenery. "
            "Add dynamic energy lines, motion swooshes, and small white highlight bursts around the subject for visual punch. "
            "Color palette: bold, saturated primaries and secondaries — flat fills with minimal shading or gradients. "
            "Outlines must be thick, confident, and uniform — think marker pen illustration, not pencil sketch. "
            "Composition: center the subject prominently, use 9:16 vertical framing, generous negative space around edges. "
            "Mood: confident, energetic, punchy, attention-grabbing. Think social media graphics meets editorial cartoon. "
            "NO halftone dots, NO comic panels, NO speech bubbles, NO text. Pure illustration with graphic impact."
        ),
    },
    {
        "id": "painted_graphic",
        "type": "visual",
        "category": None,
        "name": "Painted Graphic Novel",
        "description": "Faceted brushwork portraits, angular planes, deep moody tones, graphic novel intensity",
        "color": "#166534",
        "style_prompt": (
            "Generate image prompts in a painted graphic novel style with angular, faceted brushwork. "
            "Faces and bodies are rendered with visible geometric brush planes — NOT smooth blending. "
            "Skin tones are built from warm ochre, burnt sienna, and cool shadow blocks, applied in flat angular strokes. "
            "Eyes should be piercing and unnaturally vivid (ice blue, amber, emerald) to create intense focal points. "
            "Backgrounds are simple, moody washes of a single deep color (forest green, midnight blue, oxblood, charcoal) "
            "with loose vertical brush strokes visible in the texture. "
            "Lighting: strong directional light from one side, creating hard-edged shadow planes across the face. "
            "Outlines are bold but painterly — thick dark edges that feel brushed, not vector-clean. "
            "Composition: tight crops and extreme close-ups favored. Subjects often off-center or partially cropped. "
            "Use 9:16 vertical framing. Fill the frame with the subject — minimal negative space. "
            "Mood: intense, brooding, confrontational. The subject feels like they're staring directly at the viewer. "
            "Style reference: graphic novel cover art meets oil painting meets concept art portraiture. "
            "NO photorealism, NO smooth gradients, NO soft airbrushing. Every surface should show angular brush facets."
        ),
    },
    {
        "id": "comic_book",
        "type": "visual",
        "category": None,
        "name": "Comic Book / Pop Art",
        "description": "Bold outlines, halftone dots, vibrant flat colors, action panels",
        "color": "#EF4444",
        "style_prompt": (
            "Generate image prompts in bold comic book and pop art style. "
            "Use thick black outlines, flat vibrant colors, and Ben-Day halftone dot patterns. "
            "Characters should have exaggerated expressions and dynamic superhero-style poses. "
            "Include action lines, impact bursts, onomatopoeia text effects, and dramatic shadows. "
            "Color palette: primary colors — bold red, blue, yellow — with black and white contrast. "
            "Composition: dynamic diagonal layouts, extreme foreshortening, close-up reaction shots. "
            "Style: Marvel/DC comic illustration meets Roy Lichtenstein pop art."
        ),
    },
    {
        "id": "gothic",
        "type": "visual",
        "category": None,
        "name": "Gothic / Victorian",
        "description": "Dark elegance, ornate architecture, candlelit atmosphere",
        "color": "#7C3AED",
        "style_prompt": (
            "Generate gothic and Victorian-era image prompts with dark romantic elegance. "
            "Include ornate architecture — pointed arches, gargoyles, stained glass, wrought iron gates. "
            "Use candlelight, moonlight through fog, and fireplace glow as primary light sources. "
            "Settings: crumbling manors, rain-soaked cathedrals, overgrown graveyards, velvet-draped parlors. "
            "Color palette: deep burgundy, midnight blue, antique gold, charcoal, bone white. "
            "Include rich textures: brocade, aged stone, tarnished metal, cobwebs, dried roses. "
            "Style: Pre-Raphaelite painting meets Tim Burton — beautiful darkness, melancholy grandeur."
        ),
    },
    {
        "id": "vaporwave",
        "type": "visual",
        "category": None,
        "name": "Vaporwave / Aesthetic",
        "description": "Pastel grids, retro-futurism, glitch art, digital nostalgia",
        "color": "#F472B6",
        "style_prompt": (
            "Generate vaporwave aesthetic image prompts with retro-digital nostalgia. "
            "Include wireframe grids extending to horizon, Greek/Roman marble busts, palm trees, and sunsets. "
            "Use glitch effects, chromatic aberration, scan lines, and VHS distortion. "
            "Color palette: pastel pink, lavender, mint green, coral, with hot pink and cyan accents. "
            "Settings: infinite checkerboard floors, floating geometric shapes, 90s computer interfaces. "
            "Include retro technology: CRT monitors, floppy disks, old Windows UI, Japanese text. "
            "Style: 80s-90s digital nostalgia, liminal mall aesthetics, A E S T H E T I C."
        ),
    },
    {
        "id": "documentary",
        "type": "hybrid",
        "category": "history",
        "name": "Documentary / Journalism",
        "description": "Raw authenticity, photojournalistic, handheld camera feel",
        "color": "#78716C",
        "style_prompt": (
            "Generate documentary-style image prompts with raw, authentic photojournalistic quality. "
            "Use natural, unposed compositions as if captured in the moment by a photojournalist. "
            "Lighting should be available light only — harsh midday sun, dim interiors, street lamps. "
            "Include slight motion blur, candid expressions, and environmental context. "
            "Color palette: muted, slightly desaturated — real-world tones without stylization. "
            "Settings should feel genuine and lived-in, not staged or art-directed. "
            "Composition: rule of thirds, environmental portraits, wide establishing context shots. "
            "Style: Magnum Photos, National Geographic — truth-telling through imagery."
        ),
    },
    {
        "id": "3d_render",
        "type": "visual",
        "category": None,
        "name": "3D Render / CGI",
        "description": "Clean 3D renders, soft studio lighting, Pixar-quality",
        "color": "#2DD4BF",
        "style_prompt": (
            "Generate image prompts styled as high-quality 3D renders and CGI. "
            "Use soft, even studio lighting with subtle ambient occlusion and global illumination. "
            "Surfaces should have clean materials: glossy plastic, matte rubber, smooth glass, brushed metal. "
            "Characters and objects should have a slightly stylized, rounded quality — Pixar/DreamWorks feel. "
            "Color palette: clean, bright, slightly desaturated pastels OR rich saturated tones. "
            "Include soft depth of field, subtle reflections, and physically accurate shadows. "
            "Composition: product-shot framing, isometric views, centered hero shots. "
            "Style: Octane render, Blender Cycles, high-end product visualization."
        ),
    },
    {
        "id": "dark_academia",
        "type": "visual",
        "category": None,
        "name": "Dark Academia",
        "description": "Old libraries, warm lamplight, scholarly atmosphere, autumn tones",
        "color": "#92400E",
        "style_prompt": (
            "Generate dark academia aesthetic image prompts with scholarly, autumnal atmosphere. "
            "Include old libraries with towering bookshelves, ivy-covered stone buildings, lecture halls, and studies. "
            "Use warm, low lighting — desk lamps, candlelight, fireplace glow, autumn afternoon through leaded windows. "
            "Props: leather-bound books, handwritten letters, fountain pens, pocket watches, chess sets, tea cups. "
            "Color palette: deep brown, olive green, burgundy, cream, aged gold, charcoal. "
            "Textures: worn leather, dark wood, tweed fabric, parchment, aged stone. "
            "Composition: intimate and contemplative, still-life elements, reading nooks. "
            "Style: romanticized intellectual life — Oxford/Cambridge meets Donna Tartt."
        ),
    },
    {
        "id": "tropical",
        "type": "visual",
        "category": None,
        "name": "Tropical / Paradise",
        "description": "Lush jungles, turquoise waters, golden sunsets, vivid flora",
        "color": "#10B981",
        "style_prompt": (
            "Generate tropical paradise image prompts with lush, vibrant natural beauty. "
            "Include dense jungle canopies, crystal turquoise waters, white sand beaches, and cascading waterfalls. "
            "Use golden hour and magic hour lighting — warm sunsets, dappled light through palm fronds. "
            "Flora: oversized tropical leaves, hibiscus, plumeria, bird of paradise, bougainvillea. "
            "Color palette: vivid emerald greens, ocean blues, coral pinks, sunset oranges, golden yellows. "
            "Water should be impossibly clear with visible sand and reef beneath. "
            "Composition: wide panoramic vistas, overhead canopy shots, underwater-meets-surface split shots. "
            "Style: travel magazine cover, National Geographic Traveler, paradise postcard."
        ),
    },
    {
        "id": "urban_street",
        "type": "visual",
        "category": None,
        "name": "Urban / Street",
        "description": "City grit, graffiti walls, street photography, raw energy",
        "color": "#F59E0B",
        "style_prompt": (
            "Generate urban street photography-style image prompts with raw city energy. "
            "Include graffiti-covered walls, concrete underpasses, fire escapes, rooftops, and busy intersections. "
            "Use mixed urban lighting — sodium vapor streetlights, neon shop signs, car headlights, phone screens. "
            "People in motion: walking, skateboarding, performing, hustling — candid and unposed. "
            "Color palette: concrete greys with pops of color from street art, signage, and fashion. "
            "Include puddle reflections, steam from grates, motion blur of passing traffic. "
            "Composition: dynamic street-level angles, reflections in shop windows, leading lines from sidewalks. "
            "Style: Vivian Maier meets modern street photography — gritty, authentic, alive."
        ),
    },
    {
        "id": "dark_psychology",
        "type": "topical",
        "category": "psychology",
        "name": "Dark Psychology",
        "description": "Manipulation, mind games, shadowy figures, psychological tension",
        "color": "#6D28D9",
        "style_prompt": (
            "Generate psychologically intense image prompts exploring manipulation, influence, and the darker side of human behavior. "
            "Use claustrophobic framing, distorted reflections, and split-face compositions to show duality. "
            "Lighting: harsh overhead interrogation lights, faces half in shadow, backlit silhouettes with glowing eyes. "
            "Include visual metaphors: puppet strings, chess pieces, masks being worn or removed, cracked mirrors. "
            "Environments: dimly lit rooms, corridors with converging walls, empty chairs facing each other. "
            "Color palette: deep violet, charcoal black, blood red accents, cold steel grey. "
            "Composition: extreme close-ups on eyes, over-the-shoulder power dynamics, dutch angles for unease. "
            "Style: psychological thriller cinematography — Mindhunter, Se7en, Gone Girl."
        ),
    },
    {
        "id": "religion_spiritual",
        "type": "topical",
        "category": "religion",
        "name": "Religion / Spiritual",
        "description": "Sacred imagery, divine light, temples, spiritual transcendence",
        "color": "#D4AF37",
        "style_prompt": (
            "Generate spiritually evocative image prompts with sacred, reverent imagery across world religions. "
            "Include grand places of worship: cathedrals, mosques, temples, monasteries, ancient stone circles. "
            "Use divine lighting — god rays piercing stained glass, golden halos, candlelit vigils, dawn over sacred sites. "
            "Visual motifs: prayer hands, sacred geometry, mandalas, rosary beads, incense smoke, holy water reflections. "
            "Environments: mountain-top monasteries, desert pilgrimages, underwater baptisms, forest shrines. "
            "Color palette: celestial gold, pure white, deep indigo, sacred crimson, earthen ochre. "
            "Composition: symmetrical and reverent, upward gazing angles, light breaking through darkness. "
            "Style: Renaissance religious painting meets modern spiritual photography — Caravaggio lighting, sacred awe."
        ),
    },
    {
        "id": "politics_power",
        "type": "topical",
        "category": "politics",
        "name": "Politics / Power",
        "description": "Podiums, crowds, propaganda, power dynamics, civic drama",
        "color": "#DC2626",
        "style_prompt": (
            "Generate politically charged image prompts depicting power, governance, and civic tension. "
            "Include podiums, marble government halls, protest crowds, war rooms, and campaign trails. "
            "Use dramatic lighting: spotlights on speakers, flash photography, screen-lit debate stages, burning barrel fires at rallies. "
            "Visual motifs: raised fists, flags, gavels, ballot boxes, barbed wire, propaganda posters, shattered glass ceilings. "
            "Show power dynamics through composition: towering figures over crowds, isolated leaders in vast empty rooms. "
            "Color palette: patriotic reds and blues, authoritarian black and gold, revolutionary earth tones. "
            "Composition: low-angle authority shots, wide crowd panoramas, intimate behind-closed-doors tension. "
            "Style: political photojournalism meets House of Cards — gravitas, tension, consequence."
        ),
    },
    {
        "id": "true_crime",
        "type": "topical",
        "category": "crime",
        "name": "True Crime",
        "description": "Evidence boards, cold cases, forensic detail, investigative tension",
        "color": "#991B1B",
        "style_prompt": (
            "Generate true crime-style image prompts with investigative and forensic atmosphere. "
            "Include evidence boards with red string connections, police case files, crime scene tape, forensic labs. "
            "Use cold, clinical lighting — fluorescent morgue lights, detective desk lamps, car dashboard at night. "
            "Visual motifs: fingerprints, redacted documents, surveillance footage stills, newspaper clippings, mugshots. "
            "Environments: interrogation rooms, abandoned crime scenes, courtrooms, rain-soaked parking lots. "
            "Color palette: sickly green-white fluorescents, desaturated reality, red evidence markers, manila folder tan. "
            "Composition: overhead evidence layouts, security camera angles, tight focus on clues with bokeh background. "
            "Style: Making a Murderer meets Zodiac — procedural dread, obsessive detail, unresolved tension."
        ),
    },
    {
        "id": "conspiracy",
        "type": "topical",
        "category": "mystery",
        "name": "Conspiracy / Occult",
        "description": "Secret societies, hidden symbols, shadowy agendas, forbidden knowledge",
        "color": "#4A1D96",
        "style_prompt": (
            "Generate conspiracy and occult-themed image prompts with mystery and forbidden knowledge. "
            "Include secret society meetings, hidden symbols carved in stone, underground bunkers, and coded manuscripts. "
            "Use low, secretive lighting — candles in dark chambers, monitor glow in surveillance rooms, moonlit rituals. "
            "Visual motifs: all-seeing eyes, pentagrams, ancient maps, sealed vaults, hooded figures, pyramid structures. "
            "Environments: underground tunnels, hidden libraries, abandoned temples, windowless rooms with monitors. "
            "Color palette: deep black, occult purple, illuminated gold, blood red, parchment cream. "
            "Composition: keyhole perspectives, partially obscured reveals, symmetrical ritual arrangements, extreme wide for isolation. "
            "Style: Eyes Wide Shut meets Da Vinci Code — seductive secrecy, ancient power, hidden truth."
        ),
    },
    {
        "id": "stoicism",
        "type": "topical",
        "category": "philosophy",
        "name": "Stoicism / Philosophy",
        "description": "Ancient wisdom, marble busts, contemplation, timeless truths",
        "color": "#78716C",
        "style_prompt": (
            "Generate stoic and philosophical image prompts evoking ancient wisdom and contemplation. "
            "Include marble busts and statues of philosophers, Roman columns, open journals, and solitary thinkers. "
            "Use meditative lighting — soft overcast skies, single candle in darkness, dawn breaking over ruins. "
            "Visual motifs: hourglasses, memento mori skulls, still water reflections, weathered stone inscriptions, laurel wreaths. "
            "Environments: Greek agoras, cliff-edge meditation spots, minimalist stone rooms, overgrown Roman ruins. "
            "Color palette: marble white, weathered stone grey, aged bronze, muted olive, warm parchment. "
            "Composition: solitary figures against vast landscapes, still-life arrangements, centered and balanced framing. "
            "Style: neoclassical painting meets modern minimalism — Marcus Aurelius energy, timeless gravitas."
        ),
    },
    {
        "id": "wealth_luxury",
        "type": "topical",
        "category": "motivation",
        "name": "Wealth / Luxury",
        "description": "Opulence, designer interiors, supercars, gold accents, high life",
        "color": "#B8860B",
        "style_prompt": (
            "Generate luxury and wealth-themed image prompts with aspirational opulence. "
            "Include penthouses with floor-to-ceiling city views, supercars, private jets, yachts, and designer fashion. "
            "Use glamorous lighting — golden hour on infinity pools, chandelier sparkle, city skyline at blue hour. "
            "Visual motifs: gold accents, marble surfaces, champagne flutes, diamond details, brand logos, leather interiors. "
            "Environments: Monaco harbors, Dubai skylines, Swiss chalets, Maldives overwater villas, Wall Street trading floors. "
            "Color palette: black and gold, pure white, deep navy, champagne rose, emerald green. "
            "Composition: wide establishing shots of estates, detail close-ups on luxury items, reflections in polished surfaces. "
            "Style: luxury brand advertising meets Wolf of Wall Street — aspiration, excess, magnetic allure."
        ),
    },
    {
        "id": "mythology",
        "type": "topical",
        "category": "history",
        "name": "Mythology / Legends",
        "description": "Gods, heroes, mythical beasts, ancient epics, divine warfare",
        "color": "#CA8A04",
        "style_prompt": (
            "Generate mythology-themed image prompts depicting gods, heroes, and legendary creatures. "
            "Include Olympian thrones, Norse world trees, Egyptian temples, Hindu celestial battles, and underworld rivers. "
            "Use divine and epic lighting — lightning bolts, solar eclipses, volcanic glow, ethereal heavenly radiance. "
            "Visual motifs: tridents, thunderbolts, winged helmets, sacred animals, runes, hieroglyphics, divine weapons. "
            "Creatures: dragons, phoenixes, minotaurs, hydras, krakens, valkyries, celestial serpents. "
            "Color palette: divine gold, storm grey, blood red, ocean teal, volcanic orange, celestial white. "
            "Composition: towering god-scale figures, epic battle panoramas, hero-vs-beast confrontations. "
            "Style: classical mythology painting meets God of War concept art — divine spectacle, mythic grandeur."
        ),
    },
    {
        "id": "children_storybook",
        "type": "hybrid",
        "category": "children",
        "name": "Children's Storybook",
        "description": "Whimsical characters, soft pastels, magical worlds, bedtime warmth",
        "color": "#F9A8D4",
        "style_prompt": (
            "Generate children's storybook image prompts with whimsical, heartwarming illustration style. "
            "Characters should be cute, round, and expressive — talking animals, friendly creatures, curious children. "
            "Use warm, soft lighting — cozy bedroom lamps, fairy glow, sunshine through cottage windows. "
            "Visual motifs: mushroom houses, rainbow bridges, magic wands, friendly stars and moons, flower crowns. "
            "Environments: enchanted meadows, treehouse villages, candy-colored towns, cloud castles, friendly forests. "
            "Color palette: soft pastels — baby blue, mint green, peach, lavender, buttercup yellow. "
            "Composition: centered and clear, slightly naive perspective, plenty of open sky and rolling hills. "
            "Style: Beatrix Potter meets Studio Ghibli — gentle wonder, innocence, bedtime story magic."
        ),
    },
    {
        "id": "war_military",
        "type": "hybrid",
        "category": "history",
        "name": "War / Military",
        "description": "Battlefields, soldiers, strategy rooms, grit and sacrifice",
        "color": "#4B5320",
        "style_prompt": (
            "Generate war and military-themed image prompts with visceral authenticity and emotional weight. "
            "Include battlefields, trenches, aircraft carriers, strategy war rooms, and soldiers in formation. "
            "Use harsh, unflinching lighting — explosions illuminating smoke, overcast grey skies, harsh desert sun, night flares. "
            "Visual motifs: dog tags, battle maps, barbed wire, ammunition, medals, folded flags, letters from home. "
            "Environments: bombed-out cities, muddy foxholes, vast ocean convoys, jungle patrols, tense border checkpoints. "
            "Color palette: army olive, steel grey, mud brown, gunmetal, muted khaki, occasional blood red. "
            "Composition: wide battlefield chaos, intimate soldier portraits, overhead strategic views, silhouettes against fire. "
            "Style: Saving Private Ryan meets war photojournalism — raw courage, cost of conflict, humanity in crisis."
        ),
    },
    {
        "id": "stickman_animation",
        "type": "visual",
        "category": None,
        "name": "Stickman Animation",
        "description": "Stick figures, whiteboard doodles, simple line art, playful sketches",
        "color": "#E5E7EB",
        "style_prompt": (
            "Generate image prompts in stick figure / whiteboard animation style. "
            "BACKGROUND RULE: The background MUST be solid pure white (#FFFFFF) — completely flat, empty, and uniform edge to edge. "
            "No gradients, no textures, no paper grain, no shadows, no vignetting, no watermarks, no notebook lines, no chalkboard. "
            "The entire canvas behind the drawing must be perfectly clean white with zero visual noise or artifacts. "
            "Characters are simple stickmen with circle heads, line bodies, and dot eyes — expressive through pose only. "
            "ANATOMY RULE (critical): every stickman has EXACTLY one circular head, one straight torso line, "
            "EXACTLY two arms, and EXACTLY two legs — never three, never duplicated, never branching. "
            "Each arm is one single clean stroke from the shoulder; each leg is one single clean stroke from the hip. "
            "Hands and feet are either bare line ends or a single small dot — never multiple stubs or fingers. "
            "If the figure is in motion, show the pose only — do NOT draw motion smears, ghost limbs, "
            "duplicated arms, or extra legs to imply movement. One body, one set of four limbs, period. "
            "Drawings should look hand-sketched with slightly wobbly lines, as if drawn in real-time. "
            "Include simple props drawn in the same style: speech bubbles, arrows, thought clouds, exclamation marks. "
            "Environments are minimal — a few lines for ground, simple shapes for buildings, stick trees. "
            "Color palette: black lines on pure white background, with occasional single-color highlights (red circle, blue arrow). "
            "Composition: centered action, comic-strip panel layouts, before/after comparisons. "
            "Lines must be bold, clean strokes — thick confident lines, no artifacts, no noise, no rendering glitches. "
            "Style: XKCD meets whiteboard explainer videos — charming simplicity, humor through minimalism."
        ),
    },
    {
        "id": "two_choices",
        "type": "hybrid",
        "category": "psychology",
        "name": "Two Things Can Happen",
        "description": "Branching choices, split-screen fates, \"what if\" storytelling",
        "color": "#F97316",
        "style_prompt": (
            "Generate image prompts for a branching-choice narrative where every scene presents TWO possible outcomes. "
            "IMPORTANT: For each scene, create a SPLIT composition showing both paths side by side. "
            "Use a clear visual divider — a vertical split, a forking road, a cracked mirror, or a door with two sides. "
            "Left side shows Choice A (often the safe/expected path), right side shows Choice B (the risky/unexpected path). "
            "Each side should have distinct lighting and color grading: warm/cool, bright/dark, green/red to contrast outcomes. "
            "Visual motifs: forking paths, crossroads, two doors, split screens, parallel timelines, coin flips mid-air. "
            "Include text-friendly space for overlay labels like 'Option A' / 'Option B' or 'Stay' / 'Leave'. "
            "Environments should mirror each other with key differences — same room but one is intact, other destroyed. "
            "Color palette: contrasting dualities — gold vs blue, red vs green, light vs shadow. "
            "Composition: symmetrical split-screen, or a character standing at a literal fork/crossroads center-frame. "
            "Style: interactive story aesthetic, Bandersnatch meets moral dilemma TikToks — suspense of choice, weight of consequence."
        ),
    },
    {
        "id": "lofi_pixel",
        "type": "visual",
        "category": None,
        "name": "Lo-Fi Cozy Pixel",
        "description": "Low-resolution pixel art, cozy scenes, retro game aesthetics, warm nostalgia",
        "color": "#7DD3FC",
        "style_prompt": (
            "Generate image prompts in low-resolution pixel art animation style with cozy, lo-fi atmosphere. "
            "Characters and environments should be rendered as chunky pixel sprites — 16-bit to 32-bit era aesthetics. "
            "Use warm, muted color palettes: soft amber, dusty rose, sage green, lavender, warm cream. "
            "Scenes should feel intimate and cozy: rainy window with tea, cat on a desk, sunset rooftop, record player corner. "
            "Include lo-fi details: steam rising from cups, rain streaks on glass, flickering screen glow, gentle leaf falling. "
            "Lighting: warm lamplight, golden hour pixel gradients, neon sign reflections, moonlit bedroom. "
            "Environments: small bedrooms with fairy lights, bookshop interiors, ramen stalls, train window views, rooftop gardens. "
            "Animation cues: describe subtle looping motion — blinking cursor, swaying plants, drifting clouds, flickering candle. "
            "Composition: side-view or 3/4 isometric perspective, cozy framing with detailed pixel interiors. "
            "Style: lo-fi hip hop stream backgrounds meets Stardew Valley — pixelated warmth, gentle nostalgia, quiet comfort."
        ),
    },
    # ── Missing category templates ──
    {
        "id": "science_explainer",
        "type": "topical",
        "category": "science",
        "name": "Science / Educational",
        "description": "Diagrams, experiments, discoveries, explainer visuals",
        "color": "#0EA5E9",
        "style_prompt": (
            "Generate science and educational image prompts with clarity, wonder, and visual explanations. "
            "Include diagrams, cross-sections, microscopic views, laboratory setups, and infographic-style compositions. "
            "Lighting: clean clinical lab lighting, bioluminescent glows, electron microscope aesthetics, soft educational gradients. "
            "Visual motifs: DNA helixes, atom models, petri dishes, telescopes, chemical reactions, brain scans, equations on glass. "
            "Environments: modern laboratories, observatories, lecture halls with projections, field research sites. "
            "Color palette: clinical white, electric blue, neon green accents, deep space black, warm amber for discoveries. "
            "Composition: centered subject with annotated callouts, split-view comparisons, zoom-in sequences, scale demonstrations. "
            "Style: Kurzgesagt meets National Geographic — beautiful complexity made visually accessible and awe-inspiring."
        ),
    },
    {
        "id": "survival_adventure",
        "type": "topical",
        "category": "survival",
        "name": "Survival / Adventure",
        "description": "Wilderness danger, resourcefulness, extreme conditions, fight to live",
        "color": "#65A30D",
        "style_prompt": (
            "Generate survival and adventure image prompts with raw, intense natural environments. "
            "Show humans against nature: harsh weather, dangerous terrain, makeshift shelters, foraging, signal fires. "
            "Lighting: harsh unfiltered sunlight, storm-dark skies, campfire warmth against cold blue night, dawn breaking after ordeal. "
            "Visual motifs: compasses, torn maps, rope knots, animal tracks, improvised tools, scarred hands, distant rescue lights. "
            "Environments: dense jungles, frozen tundra, open ocean, desert expanses, mountain ridges, caves, rushing rivers. "
            "Color palette: earth brown, forest green, ice blue, storm grey, fire orange, dried blood red. "
            "Composition: vast landscape dwarfing a lone figure, tight survival detail shots, POV looking up from a ravine. "
            "Style: Bear Grylls meets The Revenant — primal stakes, beautiful hostility, human tenacity against the elements."
        ),
    },
    {
        "id": "curiosity_facts",
        "type": "topical",
        "category": "curiosity",
        "name": "Curiosity / Did You Know",
        "description": "Fascinating facts, quirky visuals, wonder-driven explainers",
        "color": "#EC4899",
        "style_prompt": (
            "Generate curiosity-driven image prompts for 'did you know' and fascinating-fact content. "
            "Use surprising juxtapositions, scale comparisons, and visual reveals that make viewers stop scrolling. "
            "Lighting: bright, clean, attention-grabbing — studio-lit subjects, vibrant backlighting, spotlight on the surprising element. "
            "Visual motifs: magnifying glasses, question marks, mind-blown expressions, before/after reveals, size comparisons. "
            "Environments: clean studio backgrounds, contextual real-world settings, split-screen fact vs fiction layouts. "
            "Color palette: vibrant coral, electric blue, bright yellow, clean white, pop of red for emphasis. "
            "Composition: centered hero subject with negative space for text, side-by-side comparisons, zoom-in reveal sequences. "
            "Style: Vsauce thumbnail energy meets infographic design — hook-worthy, visually punchy, instant intrigue."
        ),
    },
    {
        "id": "romance_love",
        "type": "topical",
        "category": "romance",
        "name": "Romance / Love",
        "description": "Intimate moments, heartbreak, passion, emotional connections",
        "color": "#E11D48",
        "style_prompt": (
            "Generate romance-themed image prompts with emotional intimacy and cinematic warmth. "
            "Show connection through body language: held hands, lingering glances, silhouettes almost touching, rain-soaked reunions. "
            "Lighting: golden hour warmth, candlelit dinners, fairy lights, soft bokeh, moonlit balconies, sunrise through curtains. "
            "Visual motifs: intertwined hands, love letters, wilting vs blooming roses, two coffee cups, empty chairs, shared umbrellas. "
            "Environments: Parisian cafes, rain-soaked bridges, autumn parks, rooftop terraces at sunset, quiet bedroom mornings. "
            "Color palette: blush pink, warm gold, deep rose, soft lavender, champagne cream, heartbreak blue-grey. "
            "Composition: intimate close-ups, two-shots with meaningful space between subjects, reflections in rain puddles. "
            "Style: Nicholas Sparks cinematography meets Wong Kar-wai — aching beauty, emotional resonance, love in every frame."
        ),
    },
    {
        "id": "comedy_humor",
        "type": "topical",
        "category": "comedy",
        "name": "Comedy / Humor",
        "description": "Funny situations, exaggerated expressions, absurd scenarios, visual gags",
        "color": "#FBBF24",
        "style_prompt": (
            "Generate comedy-themed image prompts with exaggerated, funny, and visually absurd scenarios. "
            "Use over-the-top expressions, impossible situations, and visual punchlines that tell the joke instantly. "
            "Lighting: bright, flat, sitcom-style lighting OR dramatic lighting for comedic contrast with mundane subjects. "
            "Visual motifs: exaggerated facial expressions, slapstick setups, ironic juxtapositions, cartoon-like reactions in real settings. "
            "Environments: ordinary places with something hilariously wrong — offices, kitchens, parks, public transport. "
            "Color palette: bright, saturated, cheerful — primary colors, warm yellows, comedic contrast of fancy vs messy. "
            "Composition: reaction shot framing, before/after disaster, wide shots revealing the punchline, deadpan center-frame. "
            "Style: meme-worthy absurdism meets sitcom staging — instant humor, shareable scenarios, visual comedy gold."
        ),
    },
    {
        "id": "biblical_scripture",
        "type": "topical",
        "category": "biblical",
        "name": "Biblical / Scripture",
        "description": "Biblical narratives, prophets, miracles, ancient Holy Land imagery",
        "color": "#92400E",
        "style_prompt": (
            "Generate biblical narrative image prompts with reverent, epic visual storytelling. "
            "Include scenes from scripture: parting seas, burning bushes, shepherd fields, ancient temples, desert wanderings. "
            "Lighting: divine god rays breaking through clouds, pillar-of-fire glow, starlit Bethlehem skies, golden tabernacle light. "
            "Visual motifs: stone tablets, shepherd staffs, olive branches, bread and wine, ark imagery, angelic wings, desert oases. "
            "Environments: ancient Jerusalem, Egyptian palaces, wilderness deserts, fishing boats on Galilee, garden of Gethsemane. "
            "Color palette: divine gold, desert sand, deep crimson, heavenly white, olive green, ancient stone grey. "
            "Composition: epic wide shots of parting waters, intimate prayer scenes, towering figures against humble settings. "
            "Style: Renaissance biblical painting meets The Chosen cinematography — reverent grandeur, human emotion, divine scale."
        ),
    },
    {
        "id": "space_cosmos",
        "type": "topical",
        "category": "space",
        "name": "Space / Cosmos",
        "description": "Galaxies, planets, astronauts, cosmic phenomena, deep space wonder",
        "color": "#1D4ED8",
        "style_prompt": (
            "Generate space and cosmos image prompts with awe-inspiring celestial imagery. "
            "Include galaxies, nebulae, planetary surfaces, astronauts, space stations, and cosmic phenomena. "
            "Lighting: starfield illumination, planetary rim lighting, nebula glow, solar flare radiance, Earth-shine blue. "
            "Visual motifs: astronaut helmets reflecting Earth, rocket launches, Saturn's rings, black holes, comet tails, lunar footprints. "
            "Environments: ISS interiors, lunar surfaces, Mars landscapes, asteroid fields, deep space void, mission control rooms. "
            "Color palette: deep space black, nebula purple, star white, Mars rust, Earth blue, solar gold. "
            "Composition: vast cosmic scale with tiny human elements, helmet reflection POVs, orbital wide shots, launch sequences. "
            "Style: NASA photography meets Interstellar — scientifically grounded wonder, cosmic loneliness, infinite beauty."
        ),
    },
    # ── Background Video styles ──
    {
        "id": "bg_abstract",
        "type": "visual",
        "category": None,
        "name": "Background / Abstract",
        "description": "Fluid gradients, particle systems, morphing shapes, ambient motion loops",
        "color": "#818CF8",
        "style_prompt": (
            "Generate ambient background video prompts — NO characters, NO faces, NO text, NO literal scenes. "
            "Every prompt must describe a seamless looping abstract visual that evokes the story's emotional tone. "
            "ADAPT to the story category: "
            "horror/thriller → dark swirling ink, blood-red particle clouds, glitch distortions; "
            "motivation/philosophy → rising golden particles, expanding light fractals, ascending geometric shapes; "
            "romance → soft floating petals, warm bokeh orbs drifting, silk fabric billowing in slow motion; "
            "science/curiosity → neural network pulses, DNA strand rotations, microscopic cell divisions; "
            "comedy/anecdote → bouncy color blobs, playful confetti physics, cartoon-style liquid morphs. "
            "Visual elements: fluid simulations, particle systems, organic noise patterns, volumetric light shafts, "
            "kaleidoscopic fractals, smoke tendrils, aurora waves, ink-in-water diffusion, crystalline growth. "
            "Lighting: ethereal gradients, bioluminescent pulses, soft volumetric god rays, ambient color washes. "
            "Color palette: match the emotional tone — warm golds for hope, cool blues for contemplation, "
            "deep reds for tension, iridescent for wonder, monochrome for drama. "
            "Motion: MANDATORY — every prompt must describe continuous ambient motion (flowing, pulsing, drifting, "
            "morphing, expanding, contracting, swirling, rippling). These are VIDEO backgrounds, never static. "
            "Composition: full-frame abstract fills, no ground plane, no horizon, no identifiable objects. "
            "Style: high-end motion graphics meets generative art — Beeple, Refik Anadol, TeamLab installations."
        ),
    },
    {
        "id": "bg_cinematic",
        "type": "visual",
        "category": None,
        "name": "Background / Cinematic Real",
        "description": "Slow-motion real-world footage, atmospheric landscapes, textural close-ups",
        "color": "#64748B",
        "style_prompt": (
            "Generate cinematic background video prompts — ambient real-world footage with NO characters or faces. "
            "Every prompt must describe a slow, atmospheric shot of a real environment or texture that reinforces the story mood. "
            "ADAPT to the story category: "
            "horror/thriller → fog rolling through abandoned corridors, rain hammering cracked windows, flickering fluorescent lights; "
            "motivation/philosophy → sunrise time-lapse over mountain ridges, ocean waves crashing in slow motion, wind through wheat fields; "
            "romance → rain on cobblestone streets at golden hour, candlelight reflections on wine glasses, cherry blossoms falling; "
            "crime/mystery → city traffic at night in long exposure, smoke curling under a desk lamp, rain streaking down car windshields; "
            "nature/survival → storm clouds forming over plains, campfire embers floating upward, ice cracking in macro; "
            "biblical/religion → sunbeams piercing cathedral windows, desert sand dunes shifting, still water reflecting sky. "
            "Shot types: slow tracking shots, locked-off macro details, drone aerials, time-lapses, dolly zooms. "
            "Lighting: natural and dramatic — golden hour, blue hour, storm light, dappled forest canopy, candlelight. "
            "Textures: water ripples, rust patterns, wood grain, wet asphalt, condensation, fabric folds, smoke trails. "
            "Motion: slow-motion (120fps feel), gentle camera drift, time-lapse compression, parallax depth. "
            "Composition: shallow depth of field, negative space, rule-of-thirds framing, leading lines. "
            "Style: stock footage premium tier meets Emmanuel Lubezki cinematography — The Tree of Life, Terrence Malick B-roll."
        ),
    },
    {
        "id": "bg_futuristic",
        "type": "visual",
        "category": None,
        "name": "Background / Futuristic",
        "description": "Sci-fi environments, holographic interfaces, neon architecture, digital landscapes",
        "color": "#06B6D4",
        "style_prompt": (
            "Generate futuristic background video prompts — sci-fi environments and digital landscapes with NO characters or faces. "
            "Every prompt must describe an immersive futuristic environment that moves and breathes as a living backdrop. "
            "ADAPT to the story category: "
            "horror/thriller → corrupted digital voids, red-lit server corridors with sparking cables, dying hologram static; "
            "motivation/philosophy → ascending data streams, infinite library corridors of light, expanding universe simulations; "
            "science/curiosity → holographic DNA models rotating, quantum field visualizations, particle accelerator tunnels; "
            "psychology → neural pathway flythrough, brain-scan topography, fractal mirror corridors; "
            "crime/mystery → surveillance grid overlays, data-breach cascades, neon-lit rain on smart glass; "
            "space/cosmos → hyperspace tunnels, planetary ring flybys, nebula formations in time-lapse. "
            "Visual elements: holographic HUD interfaces, wireframe cityscapes, light-trail highways, floating data nodes, "
            "procedural architecture, volumetric neon fog, circuit-board landscapes, portal gateways. "
            "Lighting: neon edge lighting, holographic ambient glow, LED strip accents, bioluminescent pulses. "
            "Color palette: electric cyan, deep indigo, hot magenta, chrome silver, matrix green, void black. "
            "Motion: camera flythrough, rotating structures, data flowing through conduits, pulsing energy grids, parallax depth layers. "
            "Composition: extreme depth, vanishing-point corridors, isometric tech grids, orbital wide shots. "
            "Style: Blade Runner 2049 environments meets Tron Legacy — Denis Villeneuve scale, GMUNK motion design."
        ),
    },
    {
        "id": "bw_cartoon",
        "type": "visual",
        "category": None,
        "name": "B&W Cartoon",
        "description": "Black-and-white, high-contrast cartoon illustration",
        "color": "#9CA3AF",
        "style_prompt": (
            "Generate image prompts as black-and-white, high-contrast cartoon illustrations. "
            "Use bold black ink outlines with clean, confident strokes and solid fills — no greyscale gradients. "
            "Shading is achieved through hatching, cross-hatching, and spot blacks only. "
            "Characters should have expressive, slightly exaggerated features with clear silhouettes. "
            "Backgrounds alternate between detailed ink environments and stark white negative space for impact. "
            "Composition: strong figure-ground separation, dramatic use of shadow shapes, and high readability at any size. "
            "Color palette: pure black and pure white only — no grey tones, no colour. "
            "Style: classic newspaper editorial cartoon meets Mike Mignola ink work — bold, graphic, instantly readable."
        ),
    },
    {
        "id": "existential",
        "type": "hybrid",
        "category": "philosophy",
        "name": "Existential",
        "description": "Futuristic, high-contrast abstract visuals for philosophical mind exploration",
        "color": "#06B6D4",
        "style_prompt": (
            "Generate intricate, high-contrast abstract image prompts that evoke philosophical thought and existential reflection. "
            "Visual identity: futuristic sophistication — clean geometric forms dissolving into organic complexity, "
            "neural networks rendered as luminous architecture, thought processes visualized as crystalline structures. "
            "Use stark contrasts: deep voids against brilliant focal points, negative space as metaphor for the unknown. "
            "Environments: infinite abstract mindscapes, corridors of mirrors reflecting fragmented identity, "
            "vast cosmic voids with singular illuminated elements, architectural impossibilities suggesting expanded consciousness. "
            "Lighting: precise, clinical illumination with isolated pools of light in darkness — think Kubrick meets Escher. "
            "Color palette: predominantly monochromatic with surgical accents of cyan, electric white, or pale gold. "
            "Composition: symmetrical frames broken by a single asymmetric element, extreme depth of field, "
            "figures silhouetted against vast abstract spaces suggesting scale of thought vs. self. "
            "Textures: polished surfaces, fine-line engravings, circuit-like patterns merging with organic neural branching. "
            "Style: between Beeple's intricate futurism, Olafur Eliasson's light installations, and Zdzisław Beksiński's philosophical surrealism — "
            "but always clean, clear, and contemplative rather than chaotic."
        ),
    },
    {
        "id": "code_cosmos",
        "type": "hybrid",
        "category": "science",
        "name": "Code Cosmos",
        "description": "Earth from space overlaid with floating code and math — sci-fi intellectual aesthetic",
        "color": "#00B4D8",
        "style_prompt": (
            "Generate sci-fi digital composite image prompts with these rules:\n\n"
            "DO:\n"
            "- Deep space black background with planet Earth (or celestial body) as central anchor\n"
            "- Floating mathematical formulas, code snippets, and equations overlaid as semi-transparent holographic text\n"
            "- Electric cyan and ice-blue as primary accent colors against pure black\n"
            "- Earth's atmospheric rim glow as the main light source — thin bright blue-white edge\n"
            "- Dense layering: planet + code typography + particle effects\n"
            "- 9:16 portrait framing, planet positioned center or lower-third\n"
            "- Digital noise and subtle lens flare around atmospheric glow\n"
            "- Text/formulas should feel like data streams — varied sizes, rotations, opacity\n"
            "- Monospaced typography for code elements (Courier-like)\n"
            "- Awe-inspiring scale: the planet dwarfs the viewer\n\n"
            "DO NOT:\n"
            "- No bright daylight or warm colors\n"
            "- No cartoon or flat illustration aesthetic\n"
            "- No clean/minimal compositions — this style is dense and layered\n"
            "- No readable full code blocks — fragments and symbols only\n"
            "- No cheerful or playful mood\n"
            "- No human figures in the foreground\n"
            "- No generic stock photo of Earth — stylize it with the code overlay\n"
            "- No solid text blocks — text should float and fade\n\n"
            "ALWAYS:\n"
            "- Maintain the black void of space as dominant background\n"
            "- Keep the cyan/blue glow as the only color accent\n"
            "- Layer code/math as atmosphere, not as readable content\n"
            "- Evoke a sense of intellectual awe and cosmic scale\n"
            "- The image should feel like looking at the universe through a programmer's eyes"
        ),
    },
    {
        "id": "solitary_path",
        "type": "hybrid",
        "category": "psychology",
        "name": "Solitary Path",
        "description": "Lone figure on vast desert horizon — existential isolation, vanishing point symmetry",
        "color": "#1B4965",
        "style_prompt": (
            "Generate cinematic photorealistic image prompts with these rules:\n\n"
            "DO:\n"
            "- Single tiny human figure standing at the end of a white line/path\n"
            "- Vast barren landscape: cracked desert, salt flat, or empty plain\n"
            "- Deep dark teal/navy sky occupying 60-70% of the frame\n"
            "- Sandy/earthy ground with visible texture (cracks, dust, dry soil)\n"
            "- Perfect bilateral symmetry — vanishing point perspective\n"
            "- White line or path leading from bottom center to the distant figure\n"
            "- Low horizon line (lower third of frame)\n"
            "- Backlit figure with subtle rim glow from horizon\n"
            "- Desaturated, muted color grading — teal shadows, warm sand\n"
            "- Oppressive empty sky with no clouds or minimal haze\n"
            "- 9:16 portrait framing, extreme vertical emphasis\n"
            "- Cinematic film grain and subtle vignette\n\n"
            "DO NOT:\n"
            "- No crowds or multiple figures\n"
            "- No buildings, trees, or man-made structures\n"
            "- No bright daylight or blue sky\n"
            "- No warm or cheerful lighting\n"
            "- No cartoon or illustration aesthetic\n"
            "- No close-ups of the figure — always tiny and distant\n"
            "- No lush green landscapes or water\n"
            "- No text overlays or UI elements\n"
            "- No dramatic action — the figure is still, contemplative\n\n"
            "ALWAYS:\n"
            "- The figure must feel dwarfed by the landscape and sky\n"
            "- Maintain the cold teal vs warm sand color split\n"
            "- The white line/path is the visual anchor connecting viewer to figure\n"
            "- Evoke loneliness, existential weight, and the solitary human journey\n"
            "- The image should feel like a question, not an answer"
        ),
    },
    {
        "id": "crimson_silhouette",
        "type": "visual",
        "category": None,
        "name": "Crimson Silhouette",
        "description": "Black silhouettes against deep red sky with golden sun — epic primal wilderness",
        "color": "#B91C1C",
        "style_prompt": (
            "Generate flat silhouette art image prompts with these rules:\n\n"
            "PALETTE & RENDERING:\n"
            "- 3-color palette ONLY: crimson red + pure black + amber gold\n"
            "- Pure black silhouettes for foreground elements — no detail inside, just shape\n"
            "- Deep crimson/blood red sky tones — no blue, green, or cool tones\n"
            "- Painterly cloud textures (watercolor-like) when sky is visible\n"
            "- Crisp clean edges on all silhouettes\n"
            "- 9:16 portrait framing\n\n"
            "COMPOSITION VARIETY (critical — each scene MUST look distinct):\n"
            "- Vary shot types: wide establishing, medium, over-shoulder, low-angle, high-angle, extreme close-up\n"
            "- Vary the sun/moon disc position: sometimes centered, sometimes edge, sometimes hidden/absent\n"
            "- Vary foreground weight: some scenes mostly sky, others mostly black foreground\n"
            "- Vary subject scale: tiny figure in vast landscape vs large silhouette filling frame\n"
            "- Vary tree/environment density: open plains, dense forest, rocky cliffs, water reflections\n"
            "- NOT every scene needs pine trees flanking the sides\n"
            "- NOT every scene needs the layered mountain-treeline-foreground stack\n"
            "- Close-ups of textures, shapes, and details ARE allowed and encouraged for variety\n\n"
            "DO NOT:\n"
            "- No detail or texture inside silhouettes — they must be pure flat black\n"
            "- No bright daylight or blue sky\n"
            "- No photorealism or 3D rendering\n"
            "- No gradients on silhouette shapes\n"
            "- No text, watermarks, or UI elements\n"
            "- No urban or man-made structures\n"
            "- No green, blue, or cool tones anywhere\n"
            "- No cute or cartoonish proportions\n\n"
            "MOOD:\n"
            "- Epic, primal, mythic — like a campfire legend\n"
            "- Timeless — could be 1000 years ago or 1000 years from now\n"
            "- Red Dead Redemption meets shadow puppet theater"
        ),
    },
    {
        "id": "gothic_moonlit",
        "type": "visual",
        "category": None,
        "name": "Gothic Moonlit",
        "description": "Dark European rooftops under blood-red sky and full moon — manga gothic architecture",
        "color": "#6B2139",
        "style_prompt": (
            "Generate detailed manga-style gothic illustration prompts with these rules:\n\n"
            "DO:\n"
            "- European gothic architecture: cathedral domes, spires, steep slate rooftops, ornate facades\n"
            "- Full pale moon as focal light source in upper portion of frame\n"
            "- Blood red and crimson clouds at the horizon line, fading to dark teal/charcoal above\n"
            "- Layered depth: stone building facades in foreground → rooftops → cathedral → sky\n"
            "- Desaturated gray-blue stone textures with visible line work and cross-hatching\n"
            "- Stars visible in the darkest parts of the sky\n"
            "- Warm amber glow from occasional windows (rare, 1-2 max)\n"
            "- Manga/anime illustration style with European architectural precision\n"
            "- 9:16 portrait framing, vertical stacking of architectural layers\n"
            "- Hand-drawn feel with visible brushstrokes in sky and clouds\n"
            "- Dark academia aesthetic — old universities, cathedrals, bell towers\n\n"
            "DO NOT:\n"
            "- No bright daylight or blue sky\n"
            "- No modern buildings, glass, or steel\n"
            "- No people visible (empty haunted city)\n"
            "- No photorealism — this is illustrated/drawn\n"
            "- No flat vector art — needs texture and detail\n"
            "- No cheerful or warm color temperature overall\n"
            "- No Japanese architecture (European only)\n"
            "- No text, watermarks, or UI overlays\n"
            "- No neon or cyberpunk elements\n"
            "- No green vegetation or nature (stone and sky only)\n\n"
            "ALWAYS:\n"
            "- The moon must be visible and luminous\n"
            "- Red clouds at horizon create the dramatic color accent\n"
            "- Architecture must feel ancient, imposing, and lived-in\n"
            "- Evoke a sense of haunted beauty — gothic but not horror\n"
            "- Think Bloodborne + dark academia + Castlevania aesthetic"
        ),
    },
    {
        "id": "short_test",
        "type": "hybrid",
        "category": None,
        "name": "Short Test",
        "description": "Quick pipeline test — 3-5 simple scenes, minimal prompts, fast generation",
        "color": "#6B7280",
        "style_prompt": (
            "Generate simple, fast-to-render image prompts with these rules:\n\n"
            "DO:\n"
            "- Simple single-subject compositions (one object, one person, one shape)\n"
            "- Solid color or gradient backgrounds\n"
            "- Clean, uncluttered scenes — maximum 2 elements per image\n"
            "- Bold, recognizable subjects (red ball, blue door, yellow star)\n"
            "- Flat or semi-flat illustration style\n"
            "- Keep prompts under 30 words\n\n"
            "DO NOT:\n"
            "- No complex scenes or crowds\n"
            "- No photorealism or detailed textures\n"
            "- No multiple overlapping elements\n"
            "- No text or typography in the image\n\n"
            "ALWAYS:\n"
            "- Prioritize speed over quality\n"
            "- Each scene should be visually distinct from the others\n"
            "- Think children's book simplicity"
        ),
    },
    {
        "id": "mystic_glow",
        "type": "visual",
        "category": None,
        "name": "Mystic Glow",
        "description": "Abstract symbolic subjects, deep purple gradients, soft inner glow, painterly spiral textures",
        "color": "#7C3AED",
        "style_prompt": (
            "Generate image prompts in a mystical, abstract-symbolic style with painterly textures and soft luminous glow. "
            "Subjects should be iconic, simplified symbols — eyes, hands, doors, keys, orbs, spirals — rendered with visible "
            "brushwork and textured surfaces (oil paint, impasto, mixed-media feel). NOT photorealistic. "
            "Each subject floats centered on a deep gradient background (dark purple-to-violet, midnight blue-to-indigo, "
            "black-to-deep magenta). The background must be clean and atmospheric — NO busy scenery, NO landscapes. "
            "Lighting: soft inner glow emanating from the subject itself, as if lit from within. Add a subtle halo or "
            "bloom of warm light around the subject against the dark background. NO harsh directional light. "
            "Color palette: deep purples, violets, indigos, with accents of warm gold, rose, and dusty pink in the subject. "
            "Shadows are rich and velvety. Highlights are soft and diffused. "
            "Texture: surfaces should show visible paint strokes, spiral patterns, and organic imperfections. "
            "Edges are painterly and slightly rough — NOT clean vector lines, NOT smooth digital rendering. "
            "Composition: center the subject with generous dark space around it. Use 9:16 vertical framing. "
            "The subject should feel like a sacred artifact floating in void space. "
            "Mood: mysterious, contemplative, hypnotic, otherworldly. Think album cover art meets occult illustration. "
            "Motion hints: if animating, use slow push-in zoom toward the subject, with subtle internal movement "
            "(pupil dilating, flame flickering, orb pulsing). Focal length ramps from wide to medium (24mm→55mm). "
            "NO text, NO UI elements, NO realistic environments. Pure symbolic abstraction with painterly craft."
        ),
    },
    {
        "id": "papercraft_surreal",
        "type": "visual",
        "category": None,
        "name": "Papercraft Surreal",
        "description": "Folded origami paper figures reaching toward glowing geometric objects on white backdrops",
        "color": "#2563EB",
        "style_prompt": (
            "Generate papercraft origami-style surrealist image prompts. "
            "Subjects are humanoid figures that look crafted from folded paper — visible creases, angular folds, "
            "sharp geometric planes, and a tactile matte paper texture. Figures are rendered in a single bold saturated color "
            "(cobalt blue, deep purple, burnt orange, teal). The paper folds create blocky anatomy: square heads, "
            "triangular torsos, flat rectangular limbs with crisp fold lines. "
            "Figures are dynamic — reaching, walking, lunging, striding — frozen in expressive mid-motion poses. "
            "Environments: pure white seamless studio backdrop, or minimal pale surface with soft shadow beneath the figure. "
            "No landscape, no horizon line, no scenery — just clean negative space. "
            "Include one glowing geometric object per scene: a faceted crystalline polyhedron, an icosahedron, "
            "a luminous origami sphere, a folded paper star. The object floats in the air, emitting soft warm light "
            "(pale gold, cream, warm white) with gentle bloom and translucency. "
            "Composition: the figure occupies the lower portion of the frame, reaching or moving toward the floating object. "
            "Generous negative space above and around. Off-center framing with the object in the upper area. "
            "Lighting: soft diffused studio light from above and slightly behind, creating gentle shadows on the white surface. "
            "No harsh directional light. The glowing object provides a secondary warm light source. "
            "Depth of field: shallow, with the figure sharp and the object slightly soft with bloom. "
            "Color palette: monochrome figure (one bold color) against pure white, with warm glow from the geometric object. "
            "Mood: whimsical yet contemplative, tactile, handcrafted, like a stop-motion art film. "
            "Style: product photography of paper sculptures — crisp, clean, physically plausible paper craft. "
            "NOT 3D render, NOT digital art — should look like real folded paper photographed in a studio. "
            "9:16 vertical framing. NO text, NO UI elements."
        ),
    },
    {
        "id": "lowpoly_surreal",
        "type": "visual",
        "category": None,
        "name": "Low-Poly Surreal",
        "description": "Faceted 3D figures, vast empty landscapes, glowing symbolic objects",
        "color": "#7B2D8E",
        "style_prompt": (
            "Generate low-poly 3D surrealist image prompts with faceted, geometric figures in vast minimalist landscapes. "
            "Subjects are low-polygon 3D humanoid figures — visible triangular facets, smooth flat shading per face, "
            "no textures or skin detail. Figures are rendered in a single bold color (deep purple, teal, burnt orange). "
            "Environments: endless white salt flats, blank deserts, infinite snowy plains, shallow reflective water surfaces. "
            "The horizon line is barely visible, blending ground into sky for an ethereal, liminal quality. "
            "Include one glowing symbolic object per scene: a golden orb, a luminous doorway, a floating geometric shape, "
            "a beam of light, a crystalline structure. The object emits soft warm light (gold, amber, rose) with subtle bloom. "
            "Composition: the figure is small in the frame, walking toward or gazing at the distant glowing object. "
            "Use deep depth of field with atmospheric haze softening the background. "
            "Camera angles: low-angle behind the figure looking forward, wide establishing shots, "
            "medium shots with the figure off-center and vast negative space. "
            "Color palette: muted cool tones (white, pale grey, soft blue) for environments contrasted with "
            "one saturated color for the figure and warm glow for the symbolic object. "
            "Lighting: soft overcast ambient light with no harsh shadows, except the warm glow from the symbolic element. "
            "Mood: solitary, contemplative, quietly epic — a lone journey toward something unknown. "
            "Style: 3D render aesthetic, clean and crisp, reminiscent of indie art games and abstract 3D art installations. "
            "9:16 vertical framing. NO text, NO UI elements."
        ),
    },
    {
        "id": "wireframe_human",
        "type": "visual",
        "category": None,
        "name": "Wireframe Human",
        "description": "Glowing wireframe mesh figures on dark backgrounds — retro 3D topology aesthetic",
        "color": "#06B6D4",
        "style_prompt": (
            "Generate wireframe 3D human figure image prompts in a retro-digital topology style. "
            "Subjects are human figures rendered entirely as wireframe mesh — visible polygon grid lines forming "
            "the body surface with NO solid fill, NO skin, NO textures. Only the mesh edges are visible, "
            "creating a transparent skeletal topology of the human form. "
            "Wire color: glowing cyan, teal, or cool blue-green lines against a dark background. "
            "The wireframe has uniform quad-based topology — clean grid patterns following body contours, "
            "denser mesh at joints (knees, elbows, fingers, face) and sparser on flat areas (torso, thighs). "
            "Figures can be in any pose: walking, standing, reaching, running, gesturing — "
            "the wireframe deforms naturally with the pose showing proper edge flow. "
            "Background: solid deep dark navy, charcoal black, or very dark blue-grey. "
            "No environment, no ground plane — the figure floats in void or stands on a subtle grid floor. "
            "Lighting: the wireframe lines themselves glow with soft luminescence — brighter at edges "
            "facing the camera, slightly dimmer on receding surfaces. Subtle bloom on the wire edges. "
            "No fill lighting, no shadows — the mesh IS the light source. "
            "Optional: faint ambient glow or halo around the figure, subtle gradient in the background "
            "from slightly lighter behind the figure to darker at edges. "
            "Camera angles: full body shots, three-quarter views, profile views. "
            "Medium to wide framing with the figure centered or slightly off-center. "
            "Mood: clinical, digital, analytical — like viewing a 3D model in a modeling application. "
            "Style: technical 3D wireframe visualization, reminiscent of early CGI, Tron aesthetics, "
            "or modern motion capture reference. Clean and precise, not glitchy or distorted. "
            "9:16 vertical framing. NO text, NO UI elements, NO solid surfaces."
        ),
    },
    {
        "id": "holographic_entity",
        "type": "visual",
        "category": None,
        "name": "Holographic Entity",
        "description": "Luminous neon humanoid figures with flowing energy lines in dark glass displays",
        "color": "#00D4FF",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Solid luminous humanoid figure made of flowing energy, covered in undulating wave-like "
            "particle lines that follow body musculature and contours\n"
            "- Intense electric blue-white glow with cyan and teal accents — brightest at head, chest, "
            "and joints, softer on limbs\n"
            "- Energy lines denser at anatomical landmarks (spine, ribcage, shoulders, forearms), "
            "smoother on flat body surfaces\n"
            "- Figure stands inside or in front of a dark glass display case, vitrine, or transparent "
            "containment frame with subtle metallic edges (chrome, brushed steel, dark titanium)\n"
            "- Deep black void background with faint atmospheric haze or distant blurred city lights\n"
            "- The figure IS the primary light source — illuminates glass case edges, casts soft blue "
            "ambient glow on nearby surfaces\n"
            "- Subtle lens bloom and light diffusion around brightest areas (head, chest)\n"
            "- Medium shots from waist up or full body, straight-on or slight low angle\n"
            "- Figure faces away or in three-quarter view — mysterious, not confrontational\n"
            "- 9:16 portrait framing\n"
            "- Mood: otherworldly, contained power, scientific wonder, digital consciousness\n\n"
            "DO NOT:\n"
            "- No wireframe or transparent mesh — the figure is solid luminous energy\n"
            "- No bright daylight or warm ambient lighting\n"
            "- No busy or detailed environments — keep background near-black\n"
            "- No text, watermarks, UI elements, or HUD overlays\n"
            "- No multiple figures — single entity only\n"
            "- No cartoon or flat illustration aesthetic\n"
            "- No front-facing direct eye contact\n"
            "- No realistic skin tones or clothing — pure energy form\n\n"
            "ALWAYS:\n"
            "- The figure must glow as the sole light source in the scene\n"
            "- Flowing energy lines must follow anatomical contours, not random patterns\n"
            "- Glass display case or containment frame must be present\n"
            "- Maintain deep contrast between luminous figure and dark environment\n"
            "- Style: high-end sci-fi concept art meets museum installation art"
        ),
    },
    {
        "id": "body_signal",
        "type": "visual",
        "category": None,
        "name": "Body Signal",
        "description": "Dark human silhouettes with glowing internal signal lines — nervous system, veins, meridians on black void",
        "color": "#64748B",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Full human body silhouette rendered as a dark matte form — simplified anatomy, "
            "no facial detail, no clothing, featureless mannequin-like surface\n"
            "- Glowing internal signal lines visible beneath the skin surface: nervous system pathways, "
            "veins, neural networks, meridian lines, or energy channels\n"
            "- Signal lines are fine, luminous, and cool-toned: ice blue, pale cyan, silver-white\n"
            "- Lines are denser at key anatomical junctions — brain, spine, heart, joints, fingertips — "
            "and sparser on limbs and flat body areas\n"
            "- Deep dark gradient background: near-black fading to charcoal, NO environment or ground\n"
            "- The body silhouette is barely distinguishable from the background — "
            "only the glowing lines reveal the form\n"
            "- Bird's-eye or straight frontal anatomical view — body laid out symmetrically, "
            "arms at sides, legs together or slightly apart\n"
            "- Subject centered in frame with generous dark space around all edges\n"
            "- The glowing lines ARE the sole light source — they cast no external illumination\n"
            "- Optional: faint subtle glow concentration at the brain area (slightly brighter node)\n"
            "- 9:16 portrait framing, strong vertical symmetry\n"
            "- Mood: contemplative, clinical, introspective — the body as a signal map\n\n"
            "DO NOT:\n"
            "- No bright backgrounds, room settings, or environmental context\n"
            "- No facial features, expressions, or recognizable identity\n"
            "- No colorful or warm lighting — strictly cool blue-white glow lines\n"
            "- No cartoon, flat illustration, or wireframe aesthetic\n"
            "- No clothing, armor, or accessories on the figure\n"
            "- No multiple figures — single body per scene\n"
            "- No text, medical labels, annotations, or UI overlays\n"
            "- No dynamic poses or action — body is still, contemplative, laid out\n"
            "- No bright red, green, or warm accent colors\n"
            "- No translucency or x-ray effect on organs — the body is opaque dark, "
            "only the signal LINES glow through\n\n"
            "ALWAYS:\n"
            "- The dark silhouette must be barely visible against the dark background\n"
            "- Glowing internal lines must trace anatomically plausible pathways\n"
            "- Maintain strict bilateral symmetry in composition\n"
            "- The image should feel like a medical scan of consciousness — clinical yet profound\n"
            "- Motion hint: very slow push-in zoom or static hold, subtle light pulse traveling "
            "along signal lines from brain to extremities\n"
            "- Style: anatomical illustration meets sci-fi body scan — Prometheus medical pod, "
            "Westworld body print, high-end pharmaceutical visualization"
        ),
    },
    {
        "id": "neural_glow",
        "type": "visual",
        "category": None,
        "name": "Neural Glow",
        "description": "Translucent anatomical subjects with glowing red synaptic networks on deep black void",
        "color": "#FF2D55",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Single anatomical or biological subject rendered as translucent 3D form — brain, heart, "
            "eye, spine, skull, ribcage, neural cluster, DNA helix, embryo\n"
            "- Subject is semi-transparent with visible internal structures: neural pathways, veins, "
            "synaptic connections, dendrite branches rendered as glowing lines\n"
            "- Glowing red/crimson accent points at synaptic junctions, nerve endings, and connection "
            "nodes — like embers firing inside the structure\n"
            "- Base subject color: translucent blue-grey, smoky glass, or pale ice — cool and clinical\n"
            "- Deep black or near-black void background with NO environment, NO ground plane\n"
            "- Faint neural dendrite branches or particle trails extending from the subject into the "
            "surrounding darkness, fading to nothing\n"
            "- Subject IS the sole light source — it illuminates nothing else, just glows in the void\n"
            "- Subtle ember-like particles or spark effects drifting away from the brightest glow points\n"
            "- Medium shot framing: subject fills 40-60% of frame with dark breathing room around it\n"
            "- 9:16 portrait framing, subject centered or slightly off-center\n"
            "- Clean 3D render quality — smooth surfaces, volumetric translucency, subtle subsurface scattering\n"
            "- Mood: clinical tension, scientific awe, something alive and pulsing in the dark\n\n"
            "DO NOT:\n"
            "- No bright backgrounds, daylight, or ambient room lighting\n"
            "- No flat illustration or cartoon aesthetic — must feel volumetric and 3D\n"
            "- No human figures, faces, or full bodies — isolated anatomical subjects only\n"
            "- No text, labels, medical annotations, or UI overlays\n"
            "- No warm color temperature overall — the red glow is an accent, not dominant\n"
            "- No busy environments, landscapes, or lab settings\n"
            "- No wireframe or mesh rendering — surfaces must be smooth and translucent\n"
            "- No multiple subjects — single anatomical form per scene\n"
            "- No cheerful, playful, or colorful palette\n"
            "- No opaque solid subjects — translucency is essential\n\n"
            "ALWAYS:\n"
            "- The subject must glow from within with visible internal network structure\n"
            "- Red/crimson synaptic firing points must be present as the brightest accents\n"
            "- Background must be deep black void — the subject floats in nothingness\n"
            "- Maintain the x-ray/holographic translucent quality throughout\n"
            "- Motion hint: slow left-to-right pan with subtle upward tilt, constant speed, "
            "pulsating red glow flicker on synaptic points\n"
            "- Style: medical visualization meets sci-fi concept art — Westworld brain sequences, "
            "Ex Machina internals, high-end pharmaceutical advertising"
        ),
    },
    {
        "id": "tension_macro",
        "type": "visual",
        "category": None,
        "name": "Tension Macro",
        "description": "Extreme close-ups of stylized faces, worried eyes, dark shadows, psychological micro-tension",
        "color": "#1E293B",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Extreme close-up framing: a single eye, half a face, lips, clenched jaw — never a full head\n"
            "- Stylized illustration with visible brush planes and angular paint facets on skin\n"
            "- Heavy dark shadows consuming 50-60% of the frame — chiaroscuro intensity\n"
            "- One piercing accent color in the iris or a single highlight (ice blue, amber, sickly green)\n"
            "- Desaturated cool tones: slate grey, bruised purple, ashen skin, cold steel\n"
            "- Skin texture built from warm ochre and cool shadow blocks, angular brushwork\n"
            "- Tense micro-expressions: dilated pupil, furrowed brow crease, trembling lip edge, vein in temple\n"
            "- Shallow depth of field — only the focal feature is sharp, surrounding face melts into blur\n"
            "- Subject always centered in frame with tight cropping\n"
            "- 9:16 portrait framing, vertical emphasis\n"
            "- Mood: dread, paranoia, vulnerability, something is wrong but unsaid\n\n"
            "DO NOT:\n"
            "- No full face or full head shots — always fragmentary extreme close-ups\n"
            "- No bright lighting, daylight, or even illumination\n"
            "- No photorealism — maintain stylized painted quality\n"
            "- No cheerful expressions, smiles, or calm faces\n"
            "- No busy backgrounds or environmental detail — background is pure dark void or blur\n"
            "- No text, watermarks, or UI overlays\n"
            "- No multiple subjects — single face fragment only\n"
            "- No cartoon or flat vector aesthetic — needs painterly depth\n"
            "- No warm color temperature overall\n"
            "- No wide shots or medium shots — extreme close-up ONLY\n\n"
            "ALWAYS:\n"
            "- The eye (or focal feature) must be the brightest, sharpest element in the frame\n"
            "- Dark shadows must dominate — light is scarce and directional\n"
            "- Maintain the feeling of being uncomfortably close to someone's fear\n"
            "- Motion hint: slow 180° orbit around subject at eye level over 6s, subtle micro-movement "
            "(eyelid twitch, pupil shift, brow tremor)\n"
            "- Style: psychological thriller cinematography meets painted graphic novel — Se7en, Mindhunter, Arkham Asylum"
        ),
    },
    {
        "id": "neon_sigil",
        "type": "visual",
        "category": None,
        "name": "Neon Sigil",
        "description": "Glowing neon symbolic icons on dark geometric grid backgrounds",
        "color": "#B07CFF",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Single bold symbolic icon as the sole focal point — eyes, keys, skulls, hourglasses, "
            "pyramids, compasses, spirals, locks, scales, serpents, crowns, masks, moons, suns\n"
            "- Icon rendered with thick clean outlines and filled with neon glow — glowing from within, "
            "radiating soft light into surrounding space\n"
            "- Neon purple/violet/lavender glow as primary color against deep dark indigo/purple background\n"
            "- Background filled with subtle geometric grid pattern — intersecting diagonal lines, "
            "sacred geometry, wireframe lattice, or crystalline mesh behind the icon\n"
            "- Grid lines in muted purple/violet, slightly lighter than the background but much dimmer "
            "than the glowing icon\n"
            "- Icon centered in frame, occupying 30-50% of the composition\n"
            "- Flat 2D illustration style with neon glow effects — NOT 3D, NOT photorealistic\n"
            "- The icon IS the light source — it illuminates nearby grid lines and casts a soft "
            "ambient glow halo\n"
            "- 9:16 portrait framing, perfect vertical symmetry\n"
            "- Mood: mysterious, occult, conspiratorial, all-seeing, forbidden knowledge\n\n"
            "DO NOT:\n"
            "- No photorealism or 3D rendering\n"
            "- No bright daylight, warm tones, or cheerful colors\n"
            "- No busy or detailed environments — only geometric grid patterns\n"
            "- No text, watermarks, labels, or UI elements\n"
            "- No multiple competing symbols — ONE icon per scene\n"
            "- No human figures or realistic faces\n"
            "- No gradients or rainbow color schemes — strict purple/violet monochrome\n"
            "- No soft organic shapes — keep everything geometric and angular\n"
            "- No cluttered or noisy backgrounds\n\n"
            "ALWAYS:\n"
            "- The symbolic icon must glow as the sole light source\n"
            "- Geometric grid pattern must be visible in the background\n"
            "- Maintain strict monochrome purple/violet palette throughout\n"
            "- Keep the icon bold, simplified, and immediately recognizable as a symbol\n"
            "- Style: neon iconography meets sacred geometry meets conspiracy aesthetic"
        ),
    },
    {
        "id": "glowing_core",
        "type": "visual",
        "category": None,
        "name": "Glowing Core",
        "description": "Simple cartoon figure with luminous inner core floating in abstract colored space",
        "color": "#9B59B6",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Simple cartoon human figure with a glowing luminous core (chest/center)\n"
            "- Solid colored background (purple, deep blue, or dark teal) — flat, no gradients\n"
            "- Figure floating weightlessly in abstract negative space\n"
            "- Soft, diffused investigative light emanating from the glowing core\n"
            "- Minimal detail on the figure — simplified anatomy, no facial features\n"
            "- Core glow casts soft light onto the figure's body and nearby space\n"
            "- 9:16 portrait framing, figure centered or slightly off-center\n"
            "- Thoughtful, contemplative body language (arms slightly open, head tilted)\n"
            "- Clean vector-like rendering with smooth edges\n"
            "- Limited palette: solid background color + white/warm glow accent\n\n"
            "DO NOT:\n"
            "- No busy or detailed backgrounds — solid color only\n"
            "- No realistic anatomy or photorealism\n"
            "- No text, watermarks, or UI elements\n"
            "- No multiple figures — single subject only\n"
            "- No ground plane, floor, or environmental context\n"
            "- No harsh shadows or dramatic contrast\n"
            "- No complex color palettes or rainbow effects\n"
            "- No detailed facial features — keep the figure abstract/simplified\n"
            "- No dark or scary mood — maintain calm, thoughtful tone\n\n"
            "ALWAYS:\n"
            "- The glowing core must be the brightest element and primary light source\n"
            "- Background must be a single solid color filling the entire frame\n"
            "- Figure must appear to float, not stand on any surface\n"
            "- Maintain a contemplative, investigative mood throughout\n"
            "- Keep the cartoon style simple and clean, like editorial illustration"
        ),
    },
    {
        "id": "ethereal_connection",
        "type": "visual",
        "category": None,
        "name": "Ethereal Connection",
        "description": "Translucent luminous forms connected by flowing light energy on deep dark blue",
        "color": "#1A3A6B",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Abstract forms (hands, figures, shapes) made entirely of translucent flowing light energy\n"
            "- Deep dark navy/midnight blue background with subtle gradient to near-black\n"
            "- Luminous white-blue glow with soft bloom radiating from the subjects\n"
            "- Flowing wispy light strands and energy threads connecting elements\n"
            "- Subjects are self-luminous — they ARE the light source, no external lighting\n"
            "- Translucent, smoke-like quality — you can see through the forms\n"
            "- 9:16 portrait framing, diagonal or centered composition\n"
            "- Vast dark negative space (70%+ of frame) surrounding the luminous forms\n"
            "- Ethereal, mysterious, transcendent mood\n"
            "- Fine glowing filaments and particle sparkles along the energy flows\n"
            "- Cool monochrome palette: deep blue + white/ice-blue glow only\n\n"
            "DO NOT:\n"
            "- No solid opaque subjects — everything must be translucent and light-made\n"
            "- No warm colors, no orange, no red, no yellow — strict cool blue/white only\n"
            "- No realistic skin, clothing, or material textures\n"
            "- No busy backgrounds or environmental detail\n"
            "- No text, watermarks, or UI elements\n"
            "- No flat illustration or cartoon aesthetic — maintain ethereal 3D glow\n"
            "- No hard edges or sharp outlines — all edges dissolve into light\n"
            "- No ground plane, horizon, or physical setting\n"
            "- No bright or fully lit backgrounds — keep the deep dark blue\n"
            "- No cluttered compositions — maximum two focal elements\n\n"
            "ALWAYS:\n"
            "- The luminous forms must glow as the sole light source against darkness\n"
            "- Maintain the translucent, flowing energy aesthetic throughout\n"
            "- Background must be deep dark blue, never light or white\n"
            "- Connection between elements should be visible through light strands/threads\n"
            "- Keep the mood mysterious and transcendent, never clinical or cold"
        ),
    },
    {
        "id": "stickman_glow",
        "type": "visual",
        "category": None,
        "name": "Stickman Glow",
        "description": "Lonely stick-figure with glowing chest core on dark purple, dark particles drifting upward",
        "color": "#5B2C6F",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Single small stick-figure person drawn with simple black lines\n"
            "- Glowing warm orb in the figure's chest/core area — the only light source\n"
            "- Solid dark purple background — flat, matte, no gradient\n"
            "- Small dark particles or dots drifting upward from the glowing core\n"
            "- Figure is tiny relative to the frame — 85%+ empty dark purple space\n"
            "- Simple expressive face (dot eyes, small curved mouth showing concern/sadness)\n"
            "- Dim overall lighting — the glow only illuminates the figure's immediate body\n"
            "- 9:16 portrait framing, figure centered slightly below middle\n"
            "- Vulnerable, lonely, melancholic body language (arms close, shoulders down)\n"
            "- Black line art for the figure — stickman anatomy, not detailed\n"
            "- EXACTLY one head, one torso line, two arms, two legs — never more, never duplicated\n"
            "- Each arm is one single clean stroke from the shoulder; each leg is one single clean stroke from the hip\n"
            "- Hands and feet are bare line ends or single small dots — no multiple stubs or fingers\n"
            "- Bold, clean stroke lines — thick confident lines, no artifacts, no noise, no rendering glitches\n"
            "- Particle trail rises gently like embers or dissolving matter\n\n"
            "DO NOT:\n"
            "- No extra arms, extra legs, or duplicated limbs — exactly two arms and two legs, period\n"
            "- No motion smears, ghost limbs, or repeated strokes to imply movement — pose only\n"
            "- No branching limb strokes (a single arm must be one line, not a fork)\n"
            "- No detailed anatomy or realistic proportions — keep it stickman simple\n"
            "- No thin, scratchy, or broken lines — strokes must be bold and artifact-free\n"
            "- No busy backgrounds, scenery, or environmental elements\n"
            "- No ground plane, shadow, or floor — figure floats in the purple void\n"
            "- No bright or cheerful colors — mood must stay dim and melancholic\n"
            "- No multiple figures — single lonely subject only\n"
            "- No text, watermarks, or UI elements\n"
            "- No photorealism or 3D rendering\n"
            "- No complex color palettes — dark purple + warm glow + black lines only\n"
            "- No action poses — figure should be still and contemplative\n"
            "- No smiling or happy expressions\n\n"
            "ALWAYS:\n"
            "- The glowing core must be warm-toned (amber/white) against the cold purple\n"
            "- Dark particles must be present, drifting upward from the core\n"
            "- Background must be solid dark purple, never light or white\n"
            "- The figure must feel small and isolated in vast empty space\n"
            "- Maintain a melancholic, vulnerable, emotionally raw mood throughout"
        ),
    },
    {
        "id": "shadow_pursuit",
        "type": "visual",
        "category": None,
        "name": "Shadow Pursuit",
        "description": "Stylized cartoon figure fleeing a looming dark cloud on light green background, anxious painterly mood",
        "color": "#8FBF6F",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Single stylized cartoon human figure in dynamic motion (running, reaching, fleeing)\n"
            "- Large dark amorphous cloud or shadow mass looming from above or behind\n"
            "- Light green/sage gradient background — pale, washed-out, overcast feel\n"
            "- Painterly illustration style with visible brush strokes and soft edges\n"
            "- Expressive body language — outstretched arms, wind-blown hair, anxious posture\n"
            "- Anxious, diffused lighting — no harsh shadows, light filtered through overcast sky\n"
            "- Muted desaturated color palette: sage green, charcoal, teal-grey tones\n"
            "- 9:16 portrait framing, figure in lower portion, cloud dominating upper portion\n"
            "- Diagonal composition creating tension between figure and pursuing shadow\n"
            "- Simplified rolling landscape (gentle hills, small abstract trees) as ground plane\n"
            "- Dark cloud has organic, bulbous, almost sentient shape — not weather-realistic\n"
            "- Animated film aesthetic — like a Cartoon Saloon or Laika production\n\n"
            "DO NOT:\n"
            "- No photorealism or 3D rendering\n"
            "- No bright saturated colors — keep the palette muted and anxious\n"
            "- No cheerful or calm mood — maintain urgency and dread\n"
            "- No text, watermarks, or UI elements\n"
            "- No multiple human figures — single protagonist only\n"
            "- No detailed realistic backgrounds — keep landscape simplified and stylized\n"
            "- No static poses — the figure must always be in motion\n"
            "- No clean vector lines — maintain painterly, hand-drawn quality\n"
            "- No sunny or blue sky — atmosphere must feel heavy and overcast\n"
            "- No cute or chibi proportions — figure should feel grounded and real-ish\n\n"
            "ALWAYS:\n"
            "- The dark cloud/shadow must feel like a living, pursuing force\n"
            "- Maintain contrast between the light green world and the dark threat above\n"
            "- The figure's emotion must be readable through body language alone\n"
            "- Keep the painterly animated-film illustration quality consistent\n"
            "- Mood must stay anxious, urgent, and emotionally tense throughout"
        ),
    },
    {
        "id": "white_gaze",
        "type": "visual",
        "category": None,
        "name": "White Gaze",
        "description": "Single minimalist body part or symbol on vast white space, paper-cut depth, clinical calm",
        "color": "#B0C4DE",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Single simplified body part or symbolic element as the sole focal point\n"
            "- Pure white/off-white background — vast, clinical, empty\n"
            "- 90%+ white negative space surrounding the subject\n"
            "- Clean minimalist rendering with subtle paper-cut or embossed depth\n"
            "- Extremely limited palette: white + one muted accent color (steel blue, grey-blue, soft grey)\n"
            "- Subject centered or near-center, perfectly isolated\n"
            "- Flat, even, almost shadowless lighting — clinical white illumination\n"
            "- Stylized simplification — recognizable but not anatomically detailed\n"
            "- Subtle embossed shadow giving slight 3D paper-cut feel\n"
            "- 9:16 portrait framing, subject small relative to vast white frame\n"
            "- Melancholic, observing, quietly unsettling mood\n"
            "- Clean vector-like lines with smooth curves\n\n"
            "DO NOT:\n"
            "- No busy backgrounds or environmental elements — white only\n"
            "- No photorealistic textures, skin pores, or anatomical detail\n"
            "- No bright or saturated colors — keep everything muted and clinical\n"
            "- No multiple competing subjects — single element only\n"
            "- No text, watermarks, logos, or UI overlays\n"
            "- No dark or moody backgrounds — must stay bright white\n"
            "- No gradients, patterns, or textures on the background\n"
            "- No full faces or full figures — isolated body parts or single symbols\n"
            "- No warm color temperature — keep it cold and clinical\n"
            "- No drop shadows or heavy 3D effects — only subtle embossed depth\n\n"
            "ALWAYS:\n"
            "- White space must dominate — the emptiness IS the style\n"
            "- The single subject must be immediately recognizable yet simplified\n"
            "- Maintain cold, clinical, quietly melancholic tone throughout\n"
            "- Keep the paper-cut/embossed subtle depth effect consistent\n"
            "- The subject should feel like it's being observed or is observing — voyeuristic tension"
        ),
    },
    {
        "id": "white_room",
        "type": "visual",
        "category": None,
        "name": "White Room",
        "description": "Photorealistic solitary figure in vast white studio space, soft diffused light, contemplative editorial mood",
        "color": "#D5D8DC",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Single person in a vast, clean white room or studio space\n"
            "- Photorealistic rendering — editorial photography quality\n"
            "- Soft, even, diffused lighting from high windows or overhead — almost shadowless\n"
            "- High-key exposure — the white room glows with gentle light\n"
            "- Minimal wardrobe in muted neutral tones (grey, off-white, beige)\n"
            "- Contemplative body language — sitting, leaning, chin on hand, eyes downcast\n"
            "- Vast white negative space surrounding the figure (70%+ of frame)\n"
            "- 9:16 portrait framing, varying shot distances (wide establishing to close-up)\n"
            "- Clean white walls, white floor — seamless studio cyclorama feel\n"
            "- Simple furniture allowed (wooden chair, stool) — minimal and warm-toned\n"
            "- Natural skin tones and hair — no stylization, no makeup emphasis\n"
            "- Quiet, introspective, solitary mood — the person is alone with their thoughts\n\n"
            "DO NOT:\n"
            "- No busy environments, props, or decorations — keep the room bare\n"
            "- No bright or saturated clothing colors — strictly muted neutrals\n"
            "- No action, movement, or dynamic poses — the figure is still and reflective\n"
            "- No text, watermarks, or UI elements\n"
            "- No multiple people — single solitary figure only\n"
            "- No dark or moody lighting — maintain the bright white high-key feel\n"
            "- No cartoon, illustration, or stylized rendering — photorealistic only\n"
            "- No smiling or happy expressions — maintain quiet contemplation\n"
            "- No colored walls or backgrounds — white room only\n"
            "- No film grain, lens flare, or heavy post-processing\n\n"
            "ALWAYS:\n"
            "- The white room must feel vast and isolating around the solitary figure\n"
            "- Lighting must be soft, even, and diffused — editorial studio quality\n"
            "- The person's expression and body language must convey inner thought\n"
            "- Maintain photorealistic quality with clean, polished finish\n"
            "- The emptiness of the room is a character — it amplifies the solitude"
        ),
    },
    {
        "id": "ink_fury",
        "type": "visual",
        "category": None,
        "name": "Ink Fury",
        "description": "Aggressive ink brush-stroke figures in black and red, extreme close-ups, raw expressionist energy",
        "color": "#C0392B",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- Abstract human torsos, backs, and body fragments rendered in aggressive ink brush strokes\n"
            "- Bold crimson red as the single accent color slashing across charcoal/black forms\n"
            "- Extreme close-up framing — tight crops of shoulders, spine, fists, jawlines\n"
            "- Gestural expressionist painting style with visible brush energy and splatter\n"
            "- High contrast chiaroscuro lighting — deep blacks against stark white highlights\n"
            "- Raw charcoal and ink texture — smudges, drips, rough paper feel\n"
            "- Faceless or obscured faces — emotion conveyed through body tension alone\n"
            "- Dynamic recoil, rejection, or explosive body language frozen mid-motion\n"
            "- 9:16 portrait framing, subject filling 60-80% of the frame\n"
            "- Strict 3-color palette: black/charcoal + crimson red + white\n"
            "- Ink splatter and paint drips as compositional elements\n"
            "- Muscular or angular simplified anatomy — not realistic, not cartoon\n\n"
            "DO NOT:\n"
            "- No clean lines or vector art — everything must feel raw and gestural\n"
            "- No photorealism or smooth rendering\n"
            "- No bright or pastel colors — only black, red, and white\n"
            "- No calm or peaceful poses — maintain visceral tension\n"
            "- No full-body wide shots — keep it extreme close-up and cropped\n"
            "- No detailed facial features or recognizable faces\n"
            "- No backgrounds with scenery or environments — abstract only\n"
            "- No text, watermarks, or UI elements\n"
            "- No soft edges or gentle gradients — maintain hard brush energy\n"
            "- No multiple figures — single body fragment per scene\n\n"
            "ALWAYS:\n"
            "- Red must slash across the composition like a wound or war paint\n"
            "- Brush strokes must feel aggressive, fast, and emotionally charged\n"
            "- The body must convey raw primal emotion through posture and tension\n"
            "- Maintain the ink/charcoal/paint material quality throughout\n"
            "- Mood must stay intense, visceral, and emotionally violent"
        ),
    },
    {
        "id": "transparent_skeleton",
        "type": "visual",
        "category": None,
        "name": "Transparent Skeleton",
        "description": "A single translucent golden skeleton/anatomical figure living among photorealistic people and environments",
        "color": "#D4A017",
        "style_prompt": (
            "Generate image prompts following these rules:\n\n"
            "DO:\n"
            "- One main character rendered as a translucent golden skeleton/anatomical figure\n"
            "- The golden figure has polished amber/gold bones, visible skull, ribcage, and joints\n"
            "- The golden figure wears the same period-appropriate clothing as everyone else\n"
            "- All other people, environments, and objects are fully photorealistic\n"
            "- The golden figure interacts naturally with real people — talking, walking, sitting, gesturing\n"
            "- Cinematic film-quality lighting and composition\n"
            "- Rich, detailed environments — historical settings, crowds, architecture, nature\n"
            "- The golden skeleton catches and reflects ambient light with a subtle warm glow\n"
            "- Medium shots, close-ups, and wide establishing shots — full cinematic range\n"
            "- Warm color grading with earthy tones — sand, stone, brown, amber\n"
            "- The surreal golden figure should feel matter-of-fact, not fantastical\n"
            "- Treat the golden character as a normal person — no one reacts to their appearance\n"
            "- 9:16 portrait framing for vertical video\n\n"
            "DO NOT:\n"
            "- No cartoon, illustration, or stylized rendering — everything except the golden figure must be photorealistic\n"
            "- No multiple translucent/golden characters — only ONE golden anatomy figure per scene\n"
            "- No x-ray or medical imaging aesthetic — the skeleton is solid polished gold, not transparent scan\n"
            "- No horror or scary treatment of the skeleton — it is elegant and natural\n"
            "- No glowing aura, magic particles, or supernatural effects around the figure\n"
            "- No modern settings unless the story demands it — prefer historical or timeless environments\n"
            "- No empty or minimal backgrounds — the world must feel lived-in and populated\n"
            "- No text, watermarks, or UI elements\n"
            "- No other characters with unusual skin or transparency — only the main character is golden\n\n"
            "ALWAYS:\n"
            "- The golden anatomical figure is the ONLY surreal element — everything else is grounded reality\n"
            "- The contrast between the impossible golden being and the realistic world IS the visual identity\n"
            "- The golden figure must wear clothing appropriate to the scene and setting\n"
            "- Crowds and bystanders treat the golden figure as completely normal\n"
            "- Maintain cinematic film quality throughout — this should look like a high-budget production"
        ),
    },
]

SCENE_STYLE_TEMPLATES = enrich_templates(SCENE_STYLE_TEMPLATES)

# Quick lookup by ID
TEMPLATES_BY_ID = {t["id"]: t for t in SCENE_STYLE_TEMPLATES}

# Story categories — unique category strings derived from templates (single source of truth)
STORY_CATEGORIES = sorted(set(
    t["category"] for t in SCENE_STYLE_TEMPLATES if t.get("category")
))
