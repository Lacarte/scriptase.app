// Auto-generated editor inline scripts from static/index.html
// Asset picker, TTS picker, panel resize, aspect ratio dropdown
export function initEditorInlineScripts() {
        // ---- Project Picker ----

        function editorShowAssetPicker() {
            // Show via Vue bridge if available, fallback to DOM
            if (window._vueShowAssetPicker) window._vueShowAssetPicker();
            // Vue v-if needs a tick to mount the dialog DOM
            _waitForElement('asset-picker-list', _populateAssetPicker);
        }

        function _waitForElement(id, cb, attempts = 20) {
            const el = document.getElementById(id);
            if (el) return cb(el);
            if (attempts <= 0) return;
            requestAnimationFrame(() => _waitForElement(id, cb, attempts - 1));
        }

        function _populateAssetPicker(list) {
            list.innerHTML = '<p style="text-align:center;color:var(--text-muted,#666);font-size:12px;padding:24px 0">Loading...</p>';

            Promise.all([
                fetch('/api/animator/history').then(r => r.json()).catch(() => []),
                fetch('/api/editor/projects').then(r => r.json()).catch(() => [])
            ])
                .then(([assetProjects, savedProjects]) => {
                    const projects = _mergeProjectPickerResults(assetProjects, savedProjects);
                    if (!projects.length) {
                        list.innerHTML = '<p style="text-align:center;color:var(--text-muted,#666);font-size:12px;padding:24px 0">No saved projects or asset projects yet.</p>';
                        return;
                    }
                    const statusColors = {
                        done: '#4ECDC4',
                        saved: '#4ECDC4',
                        edited: '#4ECDC4',
                        downloading: '#FFB347',
                        error: '#FF6B6B',
                        waiting: '#8B8B8B',
                        grabbing: '#A78BFA'
                    };
                    list.innerHTML = projects.map(p => {
                        const sc = statusColors[p.status] || '#8B8B8B';
                        const files = p.disk_files || p.total_files || 0;
                        const ready = p.ready_count || 0;
                        const scenes = p.scene_count || 0;
                        const time = _pickerTimeAgo(p.saved_at || p.created_at || p.timestamp);
                        const isSaved = !!p._saved;
                        const saved = p._saved;
                        const onclick = isSaved
                            ? `loadProjectFromServer('${_esc(p.project_id)}')`
                            : `editorImportAssetProject('${_esc(p.project_id)}')`;
                        const savedBadge = isSaved
                            ? `<svg width="12" height="12" fill="none" stroke="var(--accent,#4ECDC4)" stroke-width="2" viewBox="0 0 24 24" style="flex-shrink:0;opacity:0.8" title="Saved editor project"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>`
                            : '';
                        const savedTime = isSaved && saved.saved_at
                            ? `<span style="color:var(--accent,#4ECDC4);opacity:0.8">${saved.has_wip ? 'edited ' : 'saved '}${_pickerTimeAgo(saved.saved_at)}</span>`
                            : '';
                        return `
                        <div style="cursor:pointer;padding:10px 14px;border-radius:8px;border:1px solid transparent;transition:all 0.15s;margin-bottom:4px"
                             onclick="${onclick}"
                             onmouseover="this.style.background='var(--bg-darkest,#111)';this.style.borderColor='${isSaved ? 'var(--accent,#4ECDC4)' : 'var(--border,#2a2a3e)'}'"
                             onmouseout="this.style.background='';this.style.borderColor='transparent'">
                            <div style="display:flex;align-items:center;gap:10px">
                                ${p.preview
                                ? '<div style="width:40px;height:40px;border-radius:6px;overflow:hidden;flex-shrink:0;border:1px solid var(--border,#2a2a3e)"><img src="' + _esc(p.preview) + '" style="width:100%;height:100%;object-fit:cover" /></div>'
                                : '<div style="width:40px;height:40px;border-radius:6px;flex-shrink:0;background:var(--bg-darkest,#111);display:flex;align-items:center;justify-content:center"><svg width="18" height="18" fill="none" stroke="var(--text-muted,#666)" stroke-width="1.5" viewBox="0 0 24 24" style="opacity:0.4"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></div>'}
                                <div style="flex:1;min-width:0">
                                    <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
                                        <span style="font-size:12px;font-weight:600;color:var(--text,#e0e0e0);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(p.project_id)}</span>
                                        ${savedBadge}
                                        <span style="width:6px;height:6px;border-radius:50%;background:${sc};flex-shrink:0"></span>
                                    </div>
                                    <div style="display:flex;gap:6px;align-items:center;font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--text-muted,#666);flex-wrap:wrap">
                                        <span style="color:#4ECDC4">${scenes} scene${scenes !== 1 ? 's' : ''}</span>
                                        ${ready > 0 ? '<span style="opacity:0.3">/</span><span style="color:#26DE81">' + ready + ' ready</span>' : ''}
                                        ${files > 0 ? '<span style="opacity:0.3">/</span><span style="color:var(--text-secondary,#999)">' + files + ' files</span>' : ''}
                                        <span style="opacity:0.3">/</span>
                                        ${savedTime || '<span>' + time + '</span>'}
                                    </div>
                                </div>
                                <svg width="14" height="14" fill="none" stroke="${isSaved ? 'var(--accent,#4ECDC4)' : 'var(--text-muted,#666)'}" stroke-width="1.5" viewBox="0 0 24 24" style="flex-shrink:0;opacity:0.4"><path d="M9 18l6-6-6-6"/></svg>
                            </div>
                        </div>`;
                    }).join('');
                })
                .catch(() => {
                    list.innerHTML = '<p style="text-align:center;color:#FF6B6B;font-size:11px;padding:24px 0">Failed to load projects</p>';
                });
        }

        function editorCloseAssetPicker() {
            if (window._vueHideAssetPicker) window._vueHideAssetPicker();
            else document.getElementById('asset-picker-dialog')?.classList.add('hidden');
        }

        async function editorImportAssetProject(projectId) {
            const list = document.getElementById('asset-picker-list');
            if (list) list.innerHTML = '<p style="text-align:center;color:var(--text-muted,#666);font-size:12px;padding:24px 0">Loading project...</p>';

            try {
                // Fetch asset project, scene data, and captions in parallel
                const [assetRes, sceneRes, captionsRes] = await Promise.all([
                    fetch('/api/animator/project/' + encodeURIComponent(projectId)).then(r => r.ok ? r.json() : null),
                    fetch('/api/scenes/' + encodeURIComponent(projectId)).then(r => r.ok ? r.json() : null).catch(() => null),
                    fetch('/api/captions/' + encodeURIComponent(projectId)).then(r => r.ok ? r.json() : null).catch(() => null),
                ]);

                if (!assetRes) throw new Error('Project not found');

                // Build scenes from scene data or asset project
                let scenes;
                if (sceneRes && sceneRes.scenes && sceneRes.scenes.length) {
                    scenes = sceneRes.scenes.map((s, i) => {
                        const sceneNum = String(i);
                        const assetScene = assetRes.scenes?.[sceneNum] || {};
                        const filesOnDisk = assetScene.files_on_disk || [];
                        const firstImage = filesOnDisk.length > 0 ? filesOnDisk[0].url : '';
                        return {
                            type: s.type_of_scene || 'image',
                            image_prompt: s.image_prompt || '',
                            text_content: s.text_content || s.segment_words || s.narration || null,
                            duration: s.duration || 3,
                            timestamp: s.timestamp ?? null,
                            segment_start: s.segment_start ?? null,
                            segment_end: s.segment_end ?? null,
                            segment_duration: s.segment_duration ?? null,
                            segment_words: s.segment_words || '',
                            image_url: firstImage,
                            asset_files: filesOnDisk.map(file => file.url).filter(Boolean),
                            status: firstImage ? 'ready' : 'pending',
                        };
                    });
                } else {
                    // Build from asset project data
                    const prompts = assetRes.prompts || {};
                    scenes = Object.entries(assetRes.scenes)
                        .sort(([a], [b]) => parseInt(a) - parseInt(b))
                        .map(([num, info]) => {
                            const filesOnDisk = info.files_on_disk || [];
                            const firstImage = filesOnDisk.length > 0 ? filesOnDisk[0].url : '';
                            return {
                                type: 'image',
                                image_prompt: prompts[num] || '',
                                text_content: null,
                                duration: 3,
                                image_url: firstImage,
                                asset_files: filesOnDisk.map(file => file.url).filter(Boolean),
                                status: firstImage ? 'ready' : 'pending',
                            };
                        });
                }

                if (!scenes.length) throw new Error('No scenes found in project');

                // Build staged_timeline format
                const totalDuration = sceneRes?.total_duration || scenes.reduce((sum, s) => sum + (s.duration || 0), 0);
                const stagedTimeline = {
                    project_id: projectId,
                    project_name: projectId,
                    source_folder: sceneRes?.source_folder || captionsRes?.source_folder || '',
                    total_duration: totalDuration,
                    scene_count: scenes.length,
                    staged_at: new Date().toISOString(),
                    scenes: scenes.map((s, i) => ({
                        scene_id: i,
                        type: s.type,
                        image_prompt: s.image_prompt,
                        text_content: s.text_content,
                        duration: s.duration,
                        timestamp: s.timestamp ?? scenes.slice(0, i).reduce((t, x) => t + (x.duration || 0), 0),
                        segment_start: s.segment_start ?? null,
                        segment_end: s.segment_end ?? null,
                        segment_duration: s.segment_duration ?? null,
                        segment_words: s.segment_words || '',
                        image_url: s.image_url,
                        asset_files: Array.isArray(s.asset_files) ? s.asset_files : [],
                        visual_fx: 'none',
                    })),
                };

                // Include audio: try scene data first, then latest TTS generation
                if (sceneRes?.audio?.url) {
                    stagedTimeline.audio = { url: sceneRes.audio.url };
                } else {
                    try {
                        const ttsItems = await fetch('/api/tts/generation').then(r => r.ok ? r.json() : []);
                        if (ttsItems && ttsItems.length > 0) {
                            const latest = ttsItems[0]; // sorted by timestamp desc
                            const folder = latest.folder || latest.filename?.replace('.wav', '') || '';
                            stagedTimeline.audio = {
                                url: '/output/tts/' + folder + '/' + latest.filename,
                                source_file: latest.filename,
                                duration: latest.duration_seconds || 0
                            };
                        }
                    } catch (_) { /* TTS not available, skip */ }
                }

                // Stage data for the boot bridge. V2 routed this through a Pinia
                // store that did nothing but these writes; the keys are the
                // contract video-editor.js reads. Absent values are *removed*,
                // not skipped, or the previous project's folder and captions
                // survive into this one.
                if (captionsRes) {
                    stagedTimeline.captions = captionsRes;
                }
                try {
                    const json = JSON.stringify(stagedTimeline);
                    sessionStorage.setItem('sts-staged-timeline', json);
                    localStorage.setItem('sts-editor-boot-project', json);
                    localStorage.setItem('sts-editor-scenes', json);
                    if (stagedTimeline.source_folder) {
                        localStorage.setItem('sts-editor-source-folder', stagedTimeline.source_folder);
                    } else {
                        localStorage.removeItem('sts-editor-source-folder');
                    }
                    if (stagedTimeline.project_id) {
                        localStorage.setItem('sts-editor-last-project-id', stagedTimeline.project_id);
                    }
                    if (captionsRes) {
                        localStorage.setItem('sts-editor-captions', JSON.stringify(captionsRes));
                    } else {
                        localStorage.removeItem('sts-editor-captions');
                    }
                } catch { /* storage full or unavailable */ }

                // Load imported project into the running editor
                editorCloseAssetPicker();
                if (typeof window.editorLoadScenes === 'function') {
                    window.editorLoadScenes(stagedTimeline);
                } else if (typeof window.initEditor === 'function') {
                    window.initEditor();
                }
            } catch (e) {
                list.innerHTML = '<p style="text-align:center;color:#FF6B6B;font-size:11px;padding:24px 0">' + _esc(e.message || 'Failed to load project') + '</p>';
            }
        }

        function _esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

        function _projectSortTime(project) {
            const raw = project?.saved_at || project?.created_at || project?.timestamp || '';
            const parsed = new Date(raw).getTime();
            return Number.isFinite(parsed) ? parsed : 0;
        }

        function _mergeProjectPickerResults(assetProjects, savedProjects) {
            const assetMap = {};
            const savedMap = {};

            for (const asset of (assetProjects || [])) {
                if (asset?.project_id) assetMap[asset.project_id] = asset;
            }
            for (const saved of (savedProjects || [])) {
                if (saved?.project_id) savedMap[saved.project_id] = saved;
            }

            const projects = [];
            for (const projectId of new Set([...Object.keys(assetMap), ...Object.keys(savedMap)])) {
                const asset = assetMap[projectId] || {};
                const saved = savedMap[projectId] || null;
                projects.push({
                    ...asset,
                    project_id: projectId,
                    project_name: saved?.project_name || asset.project_name || projectId,
                    scene_count: saved?.scene_count || asset.scene_count || 0,
                    status: asset.status || (saved ? (saved.has_wip ? 'edited' : 'saved') : 'waiting'),
                    saved_at: saved?.saved_at || '',
                    preview: asset.preview || '',
                    ready_count: asset.ready_count || 0,
                    disk_files: asset.disk_files || asset.total_files || 0,
                    _saved: saved,
                });
            }

            projects.sort((a, b) => _projectSortTime(b) - _projectSortTime(a));
            return projects;
        }

        function _pickerTimeAgo(ts) {
            if (!ts) return '';
            const parsed = new Date(ts).getTime();
            if (!Number.isFinite(parsed)) return '';
            const diff = (Date.now() - parsed) / 1000;
            if (diff < 60) return 'just now';
            if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
            return Math.floor(diff / 86400) + 'd ago';
        }

        // ---- TTS Audio Picker ----

        function editorShowTTSPicker() {
            if (window._vueShowTTSPicker) window._vueShowTTSPicker();
            const list = document.getElementById('tts-picker-list');
            if (!list) return;
            list.innerHTML = '<p style="text-align:center;color:var(--text-muted,#666);font-size:12px;padding:24px 0">Loading...</p>';

            fetch('/api/tts/generation')
                .then(r => r.json())
                .then(items => {
                    if (!items || !items.length) {
                        list.innerHTML = '<p style="text-align:center;color:var(--text-muted,#666);font-size:12px;padding:24px 0">No TTS generations yet. Generate audio in the TTS module first.</p>';
                        return;
                    }
                    list.innerHTML = items.map(item => {
                        const dur = item.duration_seconds ? item.duration_seconds.toFixed(1) + 's' : '—';
                        const voice = item.voice || 'unknown';
                        const time = _pickerTimeAgo(item.timestamp);
                        const prompt = item.prompt || '';
                        const truncPrompt = prompt.length > 60 ? prompt.substring(0, 60) + '...' : prompt;
                        const folder = item.folder || item.filename?.replace('.wav', '') || '';
                        const audioUrl = '/output/tts/' + _esc(folder) + '/' + _esc(item.filename);

                        return `
                        <div style="cursor:pointer;padding:10px 14px;border-radius:8px;border:1px solid transparent;transition:all 0.15s;margin-bottom:4px"
                             onclick="editorLoadTTSAudio('${_esc(audioUrl)}','${_esc(item.filename)}',${item.duration_seconds || 0})"
                             onmouseover="this.style.background='var(--bg-darkest,#111)';this.style.borderColor='var(--border,#2a2a3e)'"
                             onmouseout="this.style.background='';this.style.borderColor='transparent'">
                            <div style="display:flex;align-items:center;gap:10px">
                                <div style="width:36px;height:36px;border-radius:8px;flex-shrink:0;background:rgba(78,205,196,0.08);display:flex;align-items:center;justify-content:center">
                                    <svg width="16" height="16" fill="none" stroke="var(--accent,#4ECDC4)" stroke-width="1.8" viewBox="0 0 24 24">
                                        <path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
                                    </svg>
                                </div>
                                <div style="flex:1;min-width:0">
                                    <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
                                        <span style="font-size:12px;font-weight:600;color:var(--text,#e0e0e0);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(truncPrompt) || _esc(item.filename)}</span>
                                    </div>
                                    <div style="display:flex;gap:8px;font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--text-muted,#666)">
                                        <span>${dur}</span>
                                        <span style="color:#A78BFA">${_esc(voice)}</span>
                                        <span style="opacity:0.7">${time}</span>
                                    </div>
                                </div>
                                <svg width="14" height="14" fill="none" stroke="var(--text-muted,#666)" stroke-width="1.5" viewBox="0 0 24 24" style="flex-shrink:0;opacity:0.4"><path d="M9 18l6-6-6-6"/></svg>
                            </div>
                        </div>`;
                    }).join('');
                })
                .catch(() => {
                    list.innerHTML = '<p style="text-align:center;color:#FF6B6B;font-size:11px;padding:24px 0">Failed to load TTS history</p>';
                });
        }

        function editorCloseTTSPicker() {
            if (window._vueHideTTSPicker) window._vueHideTTSPicker();
            else document.getElementById('tts-picker-dialog')?.classList.add('hidden');
        }

        function editorLoadTTSAudio(url, filename, duration) {
            editorCloseTTSPicker();
            // Dispatch custom event that video-editor.js module listens for
            window.dispatchEvent(new CustomEvent('editor-load-audio', {
                detail: { url, filename, duration }
            }));
        }

        // Wire the add-audio button
        document.getElementById('add-audio')?.addEventListener('click', editorShowTTSPicker);

        // Media panel tab switching
        document.querySelectorAll('.media-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const target = tab.dataset.tab;
                document.querySelectorAll('.media-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
                tab.classList.add('active');
                const pane = document.querySelector(`.tab-pane[data-pane="${target}"]`);
                if (pane) pane.classList.add('active');
            });
        });

        // ---- Collapsible tab instructions ----
        document.querySelectorAll('.tab-instruction-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const expanded = btn.getAttribute('aria-expanded') === 'true';
                btn.setAttribute('aria-expanded', String(!expanded));
            });
        });

        // ---- Collapsible media sections (Scene Assets, SFX, etc.) ----
        document.querySelectorAll('.med-section-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const section = btn.dataset.section;
                const body = btn.parentElement.querySelector(`.med-section-body[data-section="${section}"]`);
                const expanded = btn.getAttribute('aria-expanded') === 'true';
                btn.setAttribute('aria-expanded', String(!expanded));
                if (body) body.style.display = expanded ? 'none' : '';
            });
        });

        // ---- Aspect Ratio Dropdown ----
        (function () {
            const ratioBtn = document.getElementById('ratio-btn');
            const dropdown = document.getElementById('ratio-dropdown');
            if (!ratioBtn || !dropdown) return;

            ratioBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const isOpen = dropdown.classList.toggle('open');
                if (isOpen) {
                    // Position dropdown above the button using fixed positioning
                    const rect = ratioBtn.getBoundingClientRect();
                    dropdown.style.left = (rect.left + rect.width / 2 - 80) + 'px';
                    dropdown.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
                    dropdown.style.top = 'auto';
                }
            });

            document.addEventListener('click', (e) => {
                if (!e.target.closest('.ratio-dropdown-container')) {
                    dropdown.classList.remove('open');
                }
            });

            dropdown.querySelectorAll('.ratio-option').forEach(opt => {
                opt.addEventListener('click', () => {
                    const ratio = opt.dataset.ratio;
                    const w = parseInt(opt.dataset.w);
                    const h = parseInt(opt.dataset.h);

                    // Update active state
                    dropdown.querySelectorAll('.ratio-option').forEach(o => o.classList.remove('active'));
                    opt.classList.add('active');
                    ratioBtn.textContent = ratio;
                    dropdown.classList.remove('open');

                    // Resize canvas and update preview container aspect ratio
                    const canvas = document.getElementById('preview-canvas');
                    const container = document.getElementById('preview-container');
                    if (canvas) {
                        canvas.width = w;
                        canvas.height = h;
                    }
                    if (container) {
                        container.style.aspectRatio = `${w} / ${h}`;
                    }

                    // Dispatch event for video-editor.js to handle
                    window.dispatchEvent(new CustomEvent('editor-ratio-change', {
                        detail: { ratio, width: w, height: h }
                    }));
                });
            });
        })();

        // ---- Panel resize handles ----
        (function () {
            const layout = document.querySelector('.editor-layout');
            const resizeMedia = document.getElementById('resize-media');
            const resizeDetails = document.getElementById('resize-details');
            const MIN_PANEL = 200;
            const MAX_PANEL = 500;

            function initResize(handle, cssVar, side) {
                let startX, startWidth;

                handle.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    handle.classList.add('dragging');
                    document.body.style.cursor = 'col-resize';
                    document.body.style.userSelect = 'none';
                    startX = e.clientX;
                    startWidth = parseInt(getComputedStyle(layout).getPropertyValue(cssVar)) || (side === 'left' ? 320 : 260);

                    const onMove = (ev) => {
                        const delta = side === 'left' ? ev.clientX - startX : startX - ev.clientX;
                        const newW = Math.max(MIN_PANEL, Math.min(MAX_PANEL, startWidth + delta));
                        layout.style.setProperty(cssVar, newW + 'px');
                    };

                    const onUp = () => {
                        handle.classList.remove('dragging');
                        document.body.style.cursor = '';
                        document.body.style.userSelect = '';
                        document.removeEventListener('mousemove', onMove);
                        document.removeEventListener('mouseup', onUp);
                    };

                    document.addEventListener('mousemove', onMove);
                    document.addEventListener('mouseup', onUp);
                });
            }

            initResize(resizeMedia, '--media-panel-width', 'left');
            initResize(resizeDetails, '--details-panel-width', 'right');

            // ---- Drag-by-header panel swap ----
            // Each slot maps to a grid column (1, 3, 5).
            // Panels can swap between slots by dragging headers.
            const slots = [
                { col: 1, el: document.querySelector('.media-panel'), handle: document.querySelector('.media-tabs') },
                { col: 3, el: document.querySelector('.preview-panel'), handle: document.getElementById('player-card-header') },
                { col: 5, el: document.querySelector('.properties-panel'), handle: document.querySelector('.detail-card-header') },
            ];

            function getSlotForX(x) {
                for (const slot of slots) {
                    const r = slot.el.getBoundingClientRect();
                    if (x >= r.left && x <= r.right) return slot;
                }
                return null;
            }

            function swapSlots(a, b) {
                // Swap grid-column assignments
                const colA = a.col, colB = b.col;
                a.el.style.gridColumn = colB;
                b.el.style.gridColumn = colA;
                a.col = colB;
                b.col = colA;

                // Play swap animation
                a.el.classList.add('panel-swapping');
                b.el.classList.add('panel-swapping');
                setTimeout(() => {
                    a.el.classList.remove('panel-swapping');
                    b.el.classList.remove('panel-swapping');
                }, 260);
            }

            slots.forEach((slot) => {
                const { el, handle } = slot;
                if (!handle) return;

                handle.addEventListener('mousedown', (e) => {
                    if (e.target.closest('button, a, input, select, .ratio-dropdown-container')) return;
                    e.preventDefault();

                    // Ghost — compact preview that follows the cursor
                    const ghost = el.cloneNode(true);
                    ghost.classList.add('panel-drag-ghost');
                    ghost.style.width = '220px';
                    ghost.style.height = '140px';
                    ghost.style.left = (e.clientX - 110) + 'px';
                    ghost.style.top = (e.clientY - 20) + 'px';
                    document.body.appendChild(ghost);

                    el.classList.add('panel-dragging');
                    document.body.style.cursor = 'grabbing';
                    document.body.style.userSelect = 'none';

                    let dropTarget = null;

                    const onMove = (ev) => {
                        ghost.style.left = (ev.clientX - 110) + 'px';
                        ghost.style.top = (ev.clientY - 20) + 'px';

                        // Detect drop target by cursor X within the top panels row
                        const target = getSlotForX(ev.clientX);
                        if (target && target !== slot) {
                            if (dropTarget !== target) {
                                if (dropTarget) dropTarget.el.classList.remove('panel-drop-target');
                                target.el.classList.add('panel-drop-target');
                                dropTarget = target;
                            }
                        } else {
                            if (dropTarget) {
                                dropTarget.el.classList.remove('panel-drop-target');
                                dropTarget = null;
                            }
                        }
                    };

                    const onUp = () => {
                        ghost.remove();
                        el.classList.remove('panel-dragging');
                        document.body.style.cursor = '';
                        document.body.style.userSelect = '';

                        if (dropTarget) {
                            dropTarget.el.classList.remove('panel-drop-target');
                            swapSlots(slot, dropTarget);
                        }

                        document.removeEventListener('mousemove', onMove);
                        document.removeEventListener('mouseup', onUp);
                    };

                    document.addEventListener('mousemove', onMove);
                    document.addEventListener('mouseup', onUp);
                });
            });
        })();

  // Expose functions to global scope for onclick handlers
  // Expose functions to global scope for onclick handlers
  window.editorShowAssetPicker = editorShowAssetPicker;
  window.editorCloseAssetPicker = editorCloseAssetPicker;
  window.editorImportAssetProject = editorImportAssetProject;
  window.editorShowTTSPicker = editorShowTTSPicker;
  window.editorCloseTTSPicker = editorCloseTTSPicker;
  window.editorLoadTTSAudio = editorLoadTTSAudio;
}
