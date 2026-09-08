# GameFrame3D Demo Script

Goal: let judges see, from the already-created 3D scenes, how a fixed animated frame becomes a space that can be explored from new angles. On stage, center on a stable, opens-instantly interactive demo.

Current state: pre-recording script. The main demo prefers games the user has played; it currently centers on StarCraft's Artanis and Zeratul, with Dota 2 and Diablo as later material directions. Sintel is an animated short film and the lantern stone bridge is an original text-only scene; both remain production-pipeline validation materials and do not enter the main demo first. Every presented scene is created and checked ahead of time and chosen by actual availability; the page clearly labels scenes as prerecorded. Material provenance follows ../materials/catalog.json and the shared interface follows the repository's contracts/scene.schema.json. The self-used pipeline is the team's production tool; it must pass real end-to-end verification and keep production evidence, and the live demo does not require showing upload, queuing, or real-time generation.

Show path: the showcase landing page is the Created Scenes gallery. Each entry shows the original input image beside the scene's preview; clicking "Load 3D view" opens the interactive 3D scene next to the original image. The Interactive Studio page (/web/studio.html) keeps the user-interactive generation API and the rotating viewer; it stays available but secondary and is not required on stage.

## One-minute submission video

| In-video time | On-screen action | Lines and captions | Evidence basis |
| --- | --- | --- | --- |
| 0–8 s | Open the Created Scenes page, click "Load 3D view" on the day's main scene, and rotate slowly from the reference angle to the side | "GameFrame3D turns an animated frame into a 3D scene you can explore from new angles." Show the caption "Scene created ahead of time; interaction is live." | The actual viewer and the day's production result; an old manual scene must not stand in for the new result. |
| 8–22 s | Compare the original image with the result; point out character relationships, pose, props and environment | "The characters, action and environment in the original frame become one 3D scene here." Only state what is actually preserved. | Input and output correspond; point out the single most visible preserved effect; call it the default view when the camera is unverified. |
| 22–37 s | Drag to rotate continuously, move closer to a prop or character, then pull back to the whole | "You can now view it from angles the original image never showed." | Real page interaction with complete geometry and materials; occluded parts are completions. |
| 37–49 s | Switch to the second scene created today, showing a different subject and composition | "Another frame, or a text description, can also become a scene like this." Keep the line only for input types actually produced successfully. | A second actually completed result with clear source and input type; without one, keep showing main-scene details and never fake a second example. |
| 49–60 s | Rest on the clearest scene angle; show the project and public repository address | "Today we completed our own scene production pipeline and this interactive viewing experience." Captions list the actually new contributions; the line may say "GLM carried the tool implementation forward; Astra's verified role in scene analysis and fine-tuning is documented in the corresponding production records." Model statements must match the actual production records; use no model marketing line without visible evidence. | Same-day submissions and production records support the new items; model roles are stated only as actually confirmed judgments or fixes. |

The 60 seconds is an editing allocation, not a generation duration. The video mainly shows the finished demo; the generation process need not be recorded, and actual production time and cost stay in the run evidence. Only same-day new features and results enter the contribution statement, clearly separated from the old base.

## Three-minute live demo

| Live time | Action and narration |
| --- | --- |
| 0–25 s | Start on the Created Scenes gallery with the main scene entry visible. Click "Load 3D view" and rotate to the side. State the purpose: turning a beloved animated frame into an explorable static 3D scene. State that scenes were generated ahead of time and the live interaction is a real 3D viewer. |
| 25–65 s | Use the original image beside the scene to point out the actually preserved character relationships, action, and key props. Rotate the scene and observe those contents from different angles. |
| 65–105 s | Zoom into the most expressive detail, then return to the full composition. Keep the interaction continuous so the audience sees the geometry, materials and spatial relations clearly. Use the name "source-camera view" only when the camera is verified; otherwise call it the default view. |
| 105–140 s | Scroll to the second created scene entry, load it, and show a different character count, environment, or text-creation direction from the main scene. If no good enough second example exists, keep presenting the main scene and never fill time with failed jobs or loading waits. |
| 140–165 s | Explain the team's self-used pipeline in one sentence: an image or a prompt enters the production tools on the Interactive Studio page, GLM carried the tool implementation forward, and Astra's verified role in scene analysis and fine-tuning is documented in the corresponding production records. Show one concrete contribution backed by evidence; leave detailed logs for Q&A and do not open background queuing flows. |
| 165–180 s | Return to the best scene angle, give the demo address reachable through the SSH proxy and the public repository. Summarize what was added today and end on a scene that keeps being draggable. |

No new generation job starts on stage. Scene production and loading checks finish beforehand; the three minutes present results and interaction. The finished product is reached through the SSH proxy, and interaction and material loading are verified on that path; no public tunnel is used and the production tools need not be exposed to the audience.

## Two-minute Q&A preparation

| Judge question | Answer basis |
| --- | --- |
| What did Astra do? | Point to one judgment and its actual effect from the real production records, for example subject relationships, pose, or a camera adjustment. Open before/after correction evidence on demand, and never equate a call having happened with the output changing. Later tool implementation and code finishing moved to GLM; Astra's earlier participation in development, image analysis and scene fine-tuning is described per the actual records. |
| What was made today? | Point to the same-day submissions and scene production records. Old feasibility-test images are input material; if an old manual scene is referenced, label it "an existing prerecorded scene whose pose was manually revised". |
| Is this generated in real time? | "The scenes were generated ahead of time; the interaction on stage is real-time 3D. The production pipeline is the team's own tool." If asked about production duration, read that run's real record. |
| Can the input be changed? | Answer with the image or text cases actually verified end to end; never infer overall success from the number of candidate materials; no live re-run is needed to prove it. |
| Why does the back look like this? | A single frame provides no evidence of the back; the back is a completion. Compare the parts visible in the original image separately. |
| Can the materials be used? | Sintel frames are attributed under CC BY 3.0; the user test image is confirmed usable for this event. Per-image source and license come from the materials catalog. |
| How much did it cost and how long did it take? | Read the actual model call records from production (Astra/GLM and Meshy) and state unknowns as unknown. A remaining balance is not a per-run cost. |
| Can we download and keep editing? | Answer "yes" only after actually downloading and reopening a file; name the GLB or Blender project actually provided; never claim files exist that were not generated. |

## Recording handover

Recording needs the finished main scene, an interactive viewing entry, the actual input comparison, and the statement of same-day new contributions. The second high-quality scene matching the user's game preference joins the demo once complete; real production and correction evidence is retained for verification and Q&A. The audience entry does not require an open generation API or running new images live.

The self-used pipeline's real end-to-end verification is completed by the generation work line and cannot be replaced by a fixed old scene; it is reported separately from live recording. After the web page and material loading pass real integration checks, the unique dedicated muted browser is allocated by coordination, the real pages are recorded, and the original screen capture and one-minute cut are kept. Operate only the dedicated browser and never submit competition forms.
