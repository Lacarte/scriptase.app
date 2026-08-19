// Auto-generated editor shell HTML from static/index.html
// This contains the full DOM structure the imperative video-editor.js expects
export const EDITOR_SHELL_HTML = `
    <header class="app-header">
        <div class="header-left">
            <a href="#" onclick="event.preventDefault();editorGoBack()" class="back-link"
                title="Back to Production">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M19 12H5" />
                    <path d="M12 19l-7-7 7-7" />
                </svg>
            </a>
            <h1>Video Editor</h1>
            <a href="#" onclick="event.preventDefault();editorShowAssetPicker()" class="back-link"
                title="Open another project">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                </svg>
            </a>
            <span class="project-name" id="project-name">No project loaded</span>
            <span id="save-status" class="save-status" style="display:none"></span>
        </div>
        <div class="header-right">
            <div class="history-controls">
                <div class="history-btn-group">
                    <button id="undo-btn" class="history-action-btn" title="Undo (Ctrl+Z)" disabled>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                            stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="1 4 1 10 7 10"></polyline>
                            <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
                        </svg>
                    </button>
                    <div class="history-btn-divider"></div>
                    <button id="redo-btn" class="history-action-btn" title="Redo (Ctrl+Y)" disabled>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                            stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="23 4 23 10 17 10"></polyline>
                            <path d="M20.49 15a9 9 0 1 1-2.13-9.36L23 10"></path>
                        </svg>
                    </button>
                </div>
                <div class="history-dropdown-container">
                    <button id="history-btn" class="history-action-btn history-toggle" title="View History">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="10"></circle>
                            <polyline points="12 6 12 12 16 14"></polyline>
                        </svg>
                        <span id="history-badge" class="history-badge">0</span>
                    </button>
                    <div id="history-dropdown" class="history-dropdown">
                        <div class="history-dropdown-header">
                            <span>Edit History</span>
                            <button id="clear-history-btn" class="btn-clear-history" title="Clear all history">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                    stroke-width="2">
                                    <path d="M3 6h18"></path>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"></path>
                                    <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                            </button>
                        </div>
                        <button id="share-reset-initial" class="btn-reset-initial" title="Discard all edits and revert to the original state">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FF6B6B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 105.64-11.36L1 10"/>
                            </svg>
                            Reset to Initial
                        </button>
                        <ul id="editor-history-list" class="history-list">
                            <li class="history-empty">No history yet</li>
                        </ul>
                    </div>
                </div>
            </div>
            <div class="error-dropdown-container">
                <div id="error-indicator" class="error-indicator hidden" title="Scenes with errors">
                    <span class="error-dot"></span>
                    <span id="error-count" class="error-count">0</span>
                </div>
                <div id="error-dropdown" class="error-dropdown">
                    <div class="error-dropdown-header">
                        <span>Scene Errors</span>
                    </div>
                    <ul id="error-list" class="error-list">
                        <li class="error-empty">No errors</li>
                    </ul>
                </div>
            </div>
            <span style="flex:1"></span>
            <button id="preview-json" class="btn btn-secondary" title="Preview Export JSON">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                </svg>
                JSON
            </button>
            <button id="export-share-btn" class="btn btn-stage" title="Export, Import & Share">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
                    <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
                </svg>
                Export & Share
            </button>
        </div>
    </header>

    <div class="editor-layout">
        <!-- Media Panel (CapCut-style tabbed sidebar) -->
        <aside class="media-panel">
            <nav class="media-tabs">
                <button class="media-tab active" data-tab="media">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="1.8">
                        <rect x="2" y="2" width="20" height="20" rx="2" />
                        <circle cx="8.5" cy="8.5" r="1.5" />
                        <path d="M21 15l-5-5L5 21" />
                    </svg>
                    <span>Media</span>
                </button>
                <button class="media-tab" data-tab="effects">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="1.8">
                        <path d="M12 2L2 7l10 5 10-5-10-5z" />
                        <path d="M2 17l10 5 10-5" />
                        <path d="M2 12l10 5 10-5" />
                    </svg>
                    <span>Effects</span>
                </button>
                <button class="media-tab" data-tab="transitions">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="1.8">
                        <rect x="2" y="7" width="8" height="10" rx="1" />
                        <rect x="14" y="7" width="8" height="10" rx="1" />
                        <path d="M10 12h4" stroke-dasharray="2 2" />
                    </svg>
                    <span>Transitions</span>
                </button>
                <button class="media-tab" data-tab="overlays">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="1.8">
                        <rect x="3" y="3" width="14" height="14" rx="2" opacity="0.4" />
                        <rect x="7" y="7" width="14" height="14" rx="2" />
                    </svg>
                    <span>Overlays</span>
                </button>
                <button class="media-tab" data-tab="text">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="1.8">
                        <path d="M4 7V4h16v3" />
                        <path d="M12 4v16" />
                        <path d="M8 20h8" />
                    </svg>
                    <span>Text</span>
                </button>
                <button class="media-tab" data-tab="caption">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="1.8">
                        <rect x="2" y="4" width="20" height="16" rx="2" />
                        <path d="M6 14h4" />
                        <path d="M14 14h4" />
                        <path d="M6 18h12" />
                    </svg>
                    <span>Caption</span>
                </button>
                <button class="media-tab" data-tab="adjustment">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="1.8">
                        <circle cx="12" cy="12" r="3" />
                        <path
                            d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
                    </svg>
                    <span>Adjustm.</span>
                </button>
            </nav>
            <div class="media-tab-content">
                <div class="tab-pane active" data-pane="media">
                    <div class="tab-pane-body med-pane">
                        <div class="med-card">

                            <!-- Header -->
                            <div class="med-card-header">
                                <div class="med-card-header-left">
                                    <span class="med-card-icon">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <rect x="2" y="2" width="20" height="20" rx="2"/>
                                            <circle cx="8.5" cy="8.5" r="1.5"/>
                                            <path d="M21 15l-5-5L5 21"/>
                                        </svg>
                                    </span>
                                    <div>
                                        <p class="med-card-kicker">Media</p>
                                        <h3>Asset Browser</h3>
                                    </div>
                                </div>
                                <span class="med-card-badge">
                                    <span class="med-card-badge-dot"></span>
                                    Library
                                </span>
                            </div>

                            <!-- Collapsible instruction -->
                            <div class="tab-instruction">
                                <button class="tab-instruction-toggle" aria-expanded="false">
                                    <svg class="tab-instruction-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                                    <span class="tab-instruction-label">How it works</span>
                                    <svg class="tab-instruction-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                                </button>
                                <div class="tab-instruction-body">
                                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                        <rect x="2" y="2" width="20" height="20" rx="2"/>
                                        <circle cx="8.5" cy="8.5" r="1.5"/>
                                        <path d="M21 15l-5-5L5 21"/>
                                    </svg>
                                    <p class="tab-instruction-title">Browse and manage your media</p>
                                    <p class="tab-instruction-hint">Drag scene assets onto the timeline. Browse sound effects and music to add audio. Click to preview, drag to add.</p>
                                </div>
                            </div>

                            <!-- ═══ Scene Assets ═══ -->
                            <div class="med-card-section">
                                <button class="med-card-section-header med-section-toggle" aria-expanded="true" data-section="media-assets">
                                    <svg class="med-card-section-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                                    <span class="med-card-section-icon med-card-section-icon--media">
                                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
                                    </span>
                                    <span class="med-card-section-title">Scene Assets</span>
                                    <span class="med-card-section-count med-card-section-count--media" id="scene-assets-count"></span>
                                </button>
                                <div class="med-card-section-body med-section-body" data-section="media-assets">
                                    <div class="media-empty">
                                        <p>Import a project to browse scene media</p>
                                    </div>
                                </div>
                            </div>

                            <!-- ═══ Sound Effects ═══ -->
                            <div class="med-card-section">
                                <button class="med-card-section-header med-section-toggle" aria-expanded="true" data-section="sfx-library">
                                    <svg class="med-card-section-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                                    <span class="med-card-section-icon med-card-section-icon--sfx">
                                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h4l3-9 4 18 3-9h4"/></svg>
                                    </span>
                                    <span class="med-card-section-title">Sound Effects</span>
                                    <span class="med-card-section-count med-card-section-count--sfx" id="sfx-library-count">0</span>
                                    <span class="med-card-section-action" onclick="event.stopPropagation(); window.loadSfxLibrary()" title="Reload SFX">
                                        <svg width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                                    </span>
                                </button>
                                <div class="med-card-section-body med-section-body" data-section="sfx-library">
                                    <div id="sfx-library-list" class="sfx-library-list">
                                        <div class="sfx-library-loading">Loading effects...</div>
                                    </div>
                                </div>
                            </div>

                            <!-- ═══ Music ═══ -->
                            <div class="med-card-section">
                                <button class="med-card-section-header med-section-toggle" aria-expanded="true" data-section="music-library">
                                    <svg class="med-card-section-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                                    <span class="med-card-section-icon med-card-section-icon--music">
                                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="5.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="15.5" r="2.5"/><path d="M8 17.5V5l12-2v12.5"/></svg>
                                    </span>
                                    <span class="med-card-section-title">Music</span>
                                    <span class="med-card-section-count med-card-section-count--music" id="music-library-count">0</span>
                                    <span class="med-card-section-action" onclick="event.stopPropagation(); window.loadMusicLibrary()" title="Reload music">
                                        <svg width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                                    </span>
                                </button>
                                <div class="med-card-section-body med-section-body" data-section="music-library">
                                    <div id="music-library-list" class="music-library-list">
                                        <div class="sfx-library-loading">Loading music...</div>
                                    </div>
                                </div>
                            </div>

                            <!-- ═══ Project Assets (injected by JS) ═══ -->
                            <div id="project-assets-slot"></div>

                        </div>
                    </div>
                </div>
                <div class="tab-pane" data-pane="effects">
                    <div class="tab-pane-body efx-pane">
                        <div class="efx-card">

                            <!-- Header -->
                            <div class="efx-card-header">
                                <div class="efx-card-header-left">
                                    <span class="efx-card-icon">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/>
                                            <circle cx="12" cy="12" r="4"/>
                                        </svg>
                                    </span>
                                    <div>
                                        <p class="efx-card-kicker">Effects</p>
                                        <h3>Motion Presets</h3>
                                    </div>
                                </div>
                                <span class="efx-card-badge">
                                    <span class="efx-card-badge-dot"></span>
                                    Ready
                                </span>
                            </div>

                            <!-- Collapsible instruction -->
                            <div class="tab-instruction">
                                <button class="tab-instruction-toggle" aria-expanded="false">
                                    <svg class="tab-instruction-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                                    <span class="tab-instruction-label">How it works</span>
                                    <svg class="tab-instruction-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                                </button>
                                <div class="tab-instruction-body">
                                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                        <circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/>
                                        <circle cx="12" cy="12" r="4"/>
                                    </svg>
                                    <p class="tab-instruction-title">Apply motion to your scenes</p>
                                    <p class="tab-instruction-hint">Click a scene on the timeline, then choose an effect. Use auto-assign for role-based presets.</p>
                                </div>
                            </div>

                            <!-- No scene selected state -->
                            <div id="fx-no-scene" class="efx-card-empty" style="display:none">
                                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                    <circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/>
                                    <circle cx="12" cy="12" r="4"/>
                                </svg>
                                <p>Select a scene to apply effects</p>
                                <p class="efx-card-empty-hint">Click any scene on the timeline to choose a motion effect for it.</p>
                            </div>

                            <!-- Effects grid -->
                            <div id="fx-grid" class="fx-grid">
                                <div class="efx-section-label">Motion Effects</div>
                                <div class="fx-card-grid efx-card-grid" id="fx-card-grid">
                                    <button class="fx-card" data-fx="static" title="No motion">
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="3" width="18" height="18" rx="2"/>
                                                <circle cx="12" cy="12" r="3"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Static</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="zoom_in" title="Slowly zoom into the scene">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <circle cx="11" cy="11" r="8"/>
                                                <path d="M21 21l-4.35-4.35"/>
                                                <path d="M11 8v6M8 11h6"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Zoom In</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="zoom_out" title="Slowly zoom out from the scene">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <circle cx="11" cy="11" r="8"/>
                                                <path d="M21 21l-4.35-4.35"/>
                                                <path d="M8 11h6"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Zoom Out</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="pan_left" title="Pan camera from right to left">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <path d="M19 12H5"/><path d="M12 5l-7 7 7 7"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Pan Left</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="pan_right" title="Pan camera from left to right">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <path d="M5 12h14"/><path d="M12 5l7 7-7 7"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Pan Right</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="fade" title="Fade in from transparent">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/>
                                                <circle cx="12" cy="12" r="4"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Fade</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="shake" title="Camera shake for impact">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <path d="M2 12l3-3 3 6 3-6 3 6 3-6 3 3"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Shake</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="pan_up" title="Pan camera from bottom to top">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <path d="M12 19V5"/><path d="M5 12l7-7 7 7"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Pan Up</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="pan_down" title="Pan camera from top to bottom">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <path d="M12 5v14"/><path d="M19 12l-7 7-7-7"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Pan Down</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="pan_diagonal_tl" title="Diagonal pan toward top-left">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <path d="M17 17L7 7"/><path d="M7 17V7h10"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Diag TL</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="pan_diagonal_br" title="Diagonal pan toward bottom-right">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <path d="M7 7l10 10"/><path d="M17 7v10H7"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Diag BR</span>
                                    </button>
                                    <button class="fx-card in-pool" data-fx="ken_burns" title="Zoom in + slow pan combined">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="3" width="18" height="18" rx="2"/>
                                                <circle cx="9" cy="9" r="3"/><path d="M15 15l3 3"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Ken Burns</span>
                                    </button>
                                </div>

                                <!-- Actions -->
                                <div class="efx-card-actions">
                                    <button class="efx-card-btn efx-card-btn-primary" id="fx-auto-assign"
                                        title="Auto-assign effects based on scene roles">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
                                        </svg>
                                        Auto-assign
                                    </button>
                                    <button class="efx-card-btn efx-card-btn-secondary" id="fx-random-assign"
                                        title="Randomly assign effects to all scenes">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <rect x="2" y="2" width="20" height="20" rx="2"/>
                                            <circle cx="8" cy="8" r="1.5" fill="currentColor"/>
                                            <circle cx="16" cy="8" r="1.5" fill="currentColor"/>
                                            <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
                                            <circle cx="8" cy="16" r="1.5" fill="currentColor"/>
                                            <circle cx="16" cy="16" r="1.5" fill="currentColor"/>
                                        </svg>
                                        <span class="fx-btn-label">Randomize</span>
                                    </button>
                                </div>
                            </div>


                        </div>
                    </div>
                </div>
                <div class="tab-pane" data-pane="transitions">
                    <div class="tab-pane-body tr-pane">
                        <div class="tr-card">

                            <!-- Header -->
                            <div class="tr-card-header">
                                <div class="tr-card-header-left">
                                    <span class="tr-card-icon">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <rect x="2" y="6" width="9" height="12" rx="1" opacity="0.5"/>
                                            <rect x="13" y="6" width="9" height="12" rx="1" opacity="0.5"/>
                                            <rect x="8" y="6" width="8" height="12" rx="1" fill="none" stroke-dasharray="2 2"/>
                                        </svg>
                                    </span>
                                    <div>
                                        <p class="tr-card-kicker">Transitions</p>
                                        <h3>Scene Flow</h3>
                                    </div>
                                </div>
                                <span class="tr-card-badge">
                                    <span class="tr-card-badge-dot"></span>
                                    Ready
                                </span>
                            </div>

                            <!-- Collapsible instruction -->
                            <div class="tab-instruction">
                                <button class="tab-instruction-toggle" aria-expanded="false">
                                    <svg class="tab-instruction-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                                    <span class="tab-instruction-label">How it works</span>
                                    <svg class="tab-instruction-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                                </button>
                                <div class="tab-instruction-body">
                                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                        <rect x="2" y="6" width="9" height="12" rx="1" opacity="0.5"/>
                                        <rect x="13" y="6" width="9" height="12" rx="1" opacity="0.5"/>
                                        <rect x="8" y="6" width="8" height="12" rx="1" fill="none" stroke-dasharray="2 2"/>
                                    </svg>
                                    <p class="tab-instruction-title">Control how scenes flow together</p>
                                    <p class="tab-instruction-hint">Select a transition for the current scene. Use auto-assign or randomize to apply to all scenes at once.</p>
                                </div>
                            </div>

                            <!-- Transitions grid -->
                            <div id="tr-grid" class="fx-grid">
                                <div class="tr-section-label">Choose Transition</div>
                                <div class="fx-card-grid tr-card-grid" id="tr-card-grid">
                                    <button class="fx-card" data-tr="none" title="No transition">
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <path d="M18 6L6 18M6 6l12 12"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">None</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="cut" title="Hard cut — instant switch">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="5" width="7" height="14" rx="1"/>
                                                <rect x="14" y="5" width="7" height="14" rx="1"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Cut</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="crossfade" title="Smooth crossfade blend">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="2" y="6" width="9" height="12" rx="1" opacity="0.5"/>
                                                <rect x="13" y="6" width="9" height="12" rx="1" opacity="0.5"/>
                                                <rect x="8" y="6" width="8" height="12" rx="1" fill="none" stroke-dasharray="2 2"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Crossfade</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="fade_black" title="Fade to black then reveal">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="5" width="18" height="14" rx="2"/>
                                                <rect x="8" y="9" width="8" height="6" rx="1" fill="currentColor" opacity="0.4"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Fade Black</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="fade_white" title="Fade to white then reveal">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="5" width="18" height="14" rx="2"/>
                                                <rect x="8" y="9" width="8" height="6" rx="1" stroke="none" fill="currentColor" opacity="0.15"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Fade White</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="slide_left" title="Slide next scene in from right">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="6" width="8" height="12" rx="1" opacity="0.4"/>
                                                <rect x="13" y="6" width="8" height="12" rx="1"/>
                                                <path d="M15 12H9m0 0l2-2m-2 2l2 2" stroke-width="1.5"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Slide Left</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="slide_right" title="Slide next scene in from left">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="6" width="8" height="12" rx="1"/>
                                                <rect x="13" y="6" width="8" height="12" rx="1" opacity="0.4"/>
                                                <path d="M9 12h6m0 0l-2-2m2 2l-2 2" stroke-width="1.5"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Slide Right</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="slide_up" title="Slide next scene in from bottom">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="5" y="3" width="14" height="8" rx="1" opacity="0.4"/>
                                                <rect x="5" y="13" width="14" height="8" rx="1"/>
                                                <path d="M12 15V9m0 0l-2 2m2-2l2 2" stroke-width="1.5"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Slide Up</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="slide_down" title="Slide next scene in from top">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="5" y="3" width="14" height="8" rx="1"/>
                                                <rect x="5" y="13" width="14" height="8" rx="1" opacity="0.4"/>
                                                <path d="M12 9v6m0 0l-2-2m2 2l2-2" stroke-width="1.5"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Slide Down</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="wipe_left" title="Wipe reveal from right to left">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="5" width="18" height="14" rx="2"/>
                                                <line x1="13" y1="5" x2="13" y2="19" stroke-width="2" opacity="0.7"/>
                                                <rect x="13" y="5" width="8" height="14" rx="0" fill="currentColor" opacity="0.15"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Wipe Left</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="wipe_right" title="Wipe reveal from left to right">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="5" width="18" height="14" rx="2"/>
                                                <line x1="11" y1="5" x2="11" y2="19" stroke-width="2" opacity="0.7"/>
                                                <rect x="3" y="5" width="8" height="14" rx="0" fill="currentColor" opacity="0.15"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Wipe Right</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="zoom_in" title="Zoom into next scene">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="6" y="8" width="12" height="8" rx="1"/>
                                                <rect x="3" y="5" width="18" height="14" rx="2" opacity="0.35"/>
                                                <path d="M12 9v6m-3-3h6" stroke-width="1.5"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Zoom In</span>
                                    </button>
                                    <button class="fx-card in-pool" data-tr="zoom_out" title="Zoom out from current scene">
                                        <span class="fx-pool-dot"></span>
                                        <div class="fx-card-icon">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                                <rect x="3" y="5" width="18" height="14" rx="2"/>
                                                <rect x="6" y="8" width="12" height="8" rx="1" opacity="0.35"/>
                                                <path d="M9 12h6" stroke-width="1.5"/>
                                            </svg>
                                        </div>
                                        <span class="fx-card-label">Zoom Out</span>
                                    </button>
                                </div>
                                <!-- Duration control -->
                                <div id="tr-duration-row" class="tr-duration-row" style="display:none">
                                    <label>Duration</label>
                                    <input type="range" id="tr-duration-slider" min="0.1" max="1.0" step="0.1" value="0.3">
                                    <span id="tr-duration-value">0.3s</span>
                                </div>
                            </div>

                            <!-- Actions (always visible) -->
                            <div class="tr-card-actions">
                                <button class="tr-card-btn tr-card-btn-primary" id="tr-auto-assign"
                                    title="Auto-assign transitions based on scene roles">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
                                    </svg>
                                    Auto-assign
                                </button>
                                <button class="tr-card-btn tr-card-btn-secondary" id="tr-random-assign"
                                    title="Randomly assign transitions to all scenes">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <rect x="2" y="2" width="20" height="20" rx="2"/>
                                        <circle cx="8" cy="8" r="1.5" fill="currentColor"/>
                                        <circle cx="16" cy="8" r="1.5" fill="currentColor"/>
                                        <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
                                        <circle cx="8" cy="16" r="1.5" fill="currentColor"/>
                                        <circle cx="16" cy="16" r="1.5" fill="currentColor"/>
                                    </svg>
                                    <span class="fx-btn-label">Randomize</span>
                                </button>
                            </div>


                        </div>
                    </div>
                </div>
                <div class="tab-pane" data-pane="overlays">
                    <div class="tab-pane-body ov-pane">
                        <div class="ov-card">

                            <!-- Header -->
                            <div class="ov-card-header">
                                <div class="ov-card-header-left">
                                    <span class="ov-card-icon">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <rect x="3" y="7" width="14" height="10" rx="2" opacity="0.5"></rect>
                                            <rect x="7" y="3" width="14" height="10" rx="2"></rect>
                                        </svg>
                                    </span>
                                    <div>
                                        <p class="ov-card-kicker">Overlays</p>
                                        <h3>Layer Stack</h3>
                                    </div>
                                </div>
                                <span class="ov-card-badge">
                                    <span class="ov-card-badge-dot"></span>
                                    <span id="ov-stack-count">0 active</span>
                                </span>
                            </div>

                            <!-- Collapsible instruction -->
                            <div class="tab-instruction">
                                <button class="tab-instruction-toggle" aria-expanded="false">
                                    <svg class="tab-instruction-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                                    <span class="tab-instruction-label">How it works</span>
                                    <svg class="tab-instruction-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                                </button>
                                <div class="tab-instruction-body">
                                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                        <rect x="3" y="7" width="14" height="10" rx="2" opacity="0.5"/>
                                        <rect x="7" y="3" width="14" height="10" rx="2"/>
                                    </svg>
                                    <p class="tab-instruction-title">Layer textures over your scenes</p>
                                    <p class="tab-instruction-hint">Click an overlay to add it to the stack. Click again to edit blend mode and opacity. Multiple overlays stack in z-order.</p>
                                </div>
                            </div>

                            <!-- Empty state -->
                            <div id="ov-no-scene" class="ov-card-empty" style="display:none">
                                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                    <rect x="3" y="7" width="14" height="10" rx="2" opacity="0.5"></rect>
                                    <rect x="7" y="3" width="14" height="10" rx="2"></rect>
                                </svg>
                                <p>No overlays available</p>
                                <p class="ov-card-empty-hint">Overlay textures will appear here once loaded from the server.</p>
                            </div>

                            <!-- Overlay grid -->
                            <div id="ov-grid">
                                <div class="ov-section-label">Choose Overlay</div>
                                <div id="ov-card-grid" class="overlay-card-grid"></div>

                                <!-- Grain panel -->
                                <div class="ov-section-divider"></div>
                                <div id="grain-panel" class="ov-grain-panel">
                                    <div class="ov-section-label">White Dot Grain</div>
                                    <label class="ov-grain-toggle">
                                        <input type="checkbox" id="grain-enabled">
                                        <span>Enable animated grain</span>
                                    </label>
                                    <div class="ov-grain-grid">
                                        <label class="ov-grain-field">
                                            <span class="ov-grain-field-label">Opacity</span>
                                            <input id="grain-opacity" type="range" min="0.00" max="0.50" step="0.01" value="0.16">
                                            <span class="ov-grain-field-val" id="grain-opacity-val">0.16</span>
                                        </label>
                                        <label class="ov-grain-field">
                                            <span class="ov-grain-field-label">Fade In (s)</span>
                                            <input id="grain-fade-in" type="range" min="0.00" max="1.00" step="0.01" value="0.12">
                                            <span class="ov-grain-field-val" id="grain-fade-in-val">0.12</span>
                                        </label>
                                        <label class="ov-grain-field">
                                            <span class="ov-grain-field-label">Hold (s)</span>
                                            <input id="grain-hold" type="range" min="0.00" max="2.00" step="0.01" value="0.65">
                                            <span class="ov-grain-field-val" id="grain-hold-val">0.65</span>
                                        </label>
                                        <label class="ov-grain-field">
                                            <span class="ov-grain-field-label">Fade Out (s)</span>
                                            <input id="grain-fade-out" type="range" min="0.00" max="3.00" step="0.01" value="1.20">
                                            <span class="ov-grain-field-val" id="grain-fade-out-val">1.20</span>
                                        </label>
                                    </div>
                                </div>
                            </div>


                        </div>
                    </div>
                </div>
                <div class="tab-pane" data-pane="text">
                    <div class="tab-pane-body text-tool-pane">
                        <div class="text-tool-card">
                            <div class="text-tool-header">
                                <div class="text-tool-header-left">
                                    <span class="text-tool-icon">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/>
                                        </svg>
                                    </span>
                                    <div>
                                        <p class="text-tool-kicker">Text Tool</p>
                                        <h3>Add to Timeline</h3>
                                    </div>
                                </div>
                                <span class="text-tool-badge">
                                    <span class="text-tool-badge-dot"></span>
                                    Live
                                </span>
                            </div>

                            <!-- Collapsible instruction -->
                            <div class="tab-instruction">
                                <button class="tab-instruction-toggle" aria-expanded="false">
                                    <svg class="tab-instruction-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                                    <span class="tab-instruction-label">How it works</span>
                                    <svg class="tab-instruction-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                                </button>
                                <div class="tab-instruction-body">
                                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                        <path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/>
                                    </svg>
                                    <p class="tab-instruction-title">Add text to your timeline</p>
                                    <p class="tab-instruction-hint">Text scenes insert after selection. Overlay mode places text on the selected image or video scene.</p>
                                </div>
                            </div>

                            <label class="text-tool-field">
                                <span>Content</span>
                                <textarea id="text-tool-content" class="text-tool-textarea" rows="4"
                                    placeholder="Type a title, hook, lower-third, or CTA..."></textarea>
                            </label>

                            <label class="text-tool-field">
                                <span>Duration (seconds)</span>
                                <input id="text-tool-duration" class="text-tool-input" type="number"
                                    min="0.5" step="0.5" value="2.0">
                            </label>

                            <div class="text-tool-field">
                                <span>Display Mode</span>
                                <div class="text-tool-mode-buttons">
                                    <button class="text-tool-mode-btn" id="text-tool-mode-full" title="Show complete text with fade animation">Full Text</button>
                                    <button class="text-tool-mode-btn active" id="text-tool-mode-emphasis" title="Show only key emphasis words">Emphasis</button>
                                </div>
                            </div>

                            <label class="text-tool-field">
                                <span>Animation</span>
                                <select id="text-tool-animation" class="text-tool-select">
                                    <option value="fade">Fade</option>
                                    <option value="flicker">Flicker (Suspenseful)</option>
                                    <option value="slam">Slam (Dramatic)</option>
                                    <option value="typewriter">Typewriter (Educational)</option>
                                    <option value="rise">Rise (Inspirational)</option>
                                    <option value="bounce">Bounce (Comedic)</option>
                                    <option value="glow_pulse">Glow Pulse (Wholesome)</option>
                                    <option value="hard_cut">Hard Cut</option>
                                    <option value="scale_pop">Scale Pop</option>
                                    <option value="slide_up">Slide Up</option>
                                    <option value="blur_in">Blur In</option>
                                </select>
                            </label>

                            <div id="text-tool-target" class="text-tool-target"></div>

                            <div class="text-tool-actions">
                                <button id="text-add-scene" class="text-tool-btn text-tool-btn-primary">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <rect x="3" y="3" width="18" height="18" rx="3"/>
                                        <path d="M12 8v8M8 12h8"/>
                                    </svg>
                                    Add Text Scene
                                </button>
                                <button id="text-add-overlay" class="text-tool-btn text-tool-btn-secondary">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <rect x="3" y="7" width="14" height="10" rx="2" opacity="0.5"/>
                                        <rect x="7" y="3" width="14" height="10" rx="2"/>
                                    </svg>
                                    Overlay on Selected Scene
                                </button>
                            </div>

                        </div>
                    </div>
                </div>
                <div class="tab-pane" data-pane="caption">
                    <div class="tab-pane-body cap-pane">
                        <div class="cap-card">

                            <!-- Header -->
                            <div class="cap-card-header">
                                <div class="cap-card-header-left">
                                    <span class="cap-card-icon">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <rect x="2" y="4" width="20" height="16" rx="2" />
                                            <path d="M6 14h4" /><path d="M14 14h4" /><path d="M6 18h12" />
                                        </svg>
                                    </span>
                                    <div>
                                        <p class="cap-card-kicker">Captions</p>
                                        <h3>Style Editor</h3>
                                    </div>
                                </div>
                                <label class="cap-card-toggle-badge" title="Enable / disable captions">
                                    <input type="checkbox" id="caption-enabled-toggle">
                                    <span class="cap-card-toggle-slider"></span>
                                    <span class="cap-card-toggle-label" data-on="On" data-off="Off">Off</span>
                                </label>
                            </div>

                            <!-- Collapsible instruction -->
                            <div class="tab-instruction">
                                <button class="tab-instruction-toggle" aria-expanded="false">
                                    <svg class="tab-instruction-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                                    <span class="tab-instruction-label">How it works</span>
                                    <svg class="tab-instruction-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                                </button>
                                <div class="tab-instruction-body">
                                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                        <rect x="2" y="4" width="20" height="16" rx="2"/>
                                        <path d="M6 14h4"/><path d="M14 14h4"/><path d="M6 18h12"/>
                                    </svg>
                                    <p class="tab-instruction-title">Style your captions</p>
                                    <p class="tab-instruction-hint">Captions sync from the Studio Captions page. Styles apply to all caption segments on the timeline.</p>
                                </div>
                            </div>

                            <!-- Empty state (no data) -->
                            <div id="caption-no-data" class="cap-card-empty">
                                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                    <rect x="2" y="4" width="20" height="16" rx="2" />
                                    <path d="M6 14h4" /><path d="M14 14h4" /><path d="M6 18h12" />
                                </svg>
                                <p>No captions loaded.</p>
                                <p class="cap-card-empty-hint">Send captions from the Studio Captions page, or they will load automatically from alignment data.</p>
                            </div>

                            <!-- Caption info (shown when data loaded) -->
                            <div id="caption-info" style="display:none">
                                <div class="cap-card-info">
                                    <span class="cap-card-info-label">Loaded</span>
                                    <span id="caption-info-count" class="cap-card-info-value">0 captions</span>
                                </div>
                            </div>

                            <!-- Style controls (shown when data loaded) -->
                            <div id="caption-style-controls" style="display:none;flex-direction:column;gap:12px">

                                <!-- Preset & Font -->
                                <div class="cap-section">
                                    <div class="cap-section-label">Preset</div>
                                    <label class="cap-card-field">
                                        <span>Style</span>
                                        <select id="cap-ed-preset" class="cap-select">
                                            <option value="bold_popup">Bold Pop-up</option>
                                            <option value="popup_highlight">Pop-up Highlight</option>
                                            <option value="popup_highlight_box">Pop-up Highlight 2</option>
                                            <option value="subtitle_bar">Subtitle Bar</option>
                                            <option value="karaoke">Karaoke</option>
                                            <option value="minimal">Minimal</option>
                                            <option value="single_line">Single Line</option>
                                            <option value="single_line_highlight">Single Line 2</option>
                                        </select>
                                    </label>
                                    <label class="cap-card-field">
                                        <span>Font</span>
                                        <select id="cap-ed-font" class="cap-select"></select>
                                    </label>
                                </div>

                                <div class="cap-section-divider"></div>

                                <!-- Typography -->
                                <div class="cap-section">
                                    <div class="cap-section-label">Typography</div>
                                    <div class="cap-row">
                                        <label class="cap-card-field">
                                            <span>Size</span>
                                            <input id="cap-ed-size" type="number" value="64" min="24" max="120" step="2" class="cap-input">
                                        </label>
                                        <label class="cap-card-field">
                                            <span>Color</span>
                                            <input id="cap-ed-color" type="color" value="#FFFFFF" class="cap-color-input">
                                        </label>
                                    </div>
                                    <div class="cap-row">
                                        <label class="cap-card-field">
                                            <span>Stroke</span>
                                            <input id="cap-ed-stroke" type="color" value="#000000" class="cap-color-input">
                                        </label>
                                        <label class="cap-card-field">
                                            <span>Stroke Width</span>
                                            <input id="cap-ed-stroke-width" type="number" value="4" min="0" max="20" step="1" class="cap-input">
                                        </label>
                                    </div>
                                </div>

                                <div class="cap-section-divider"></div>

                                <!-- Position -->
                                <div class="cap-section">
                                    <div class="cap-section-label">Position</div>
                                    <div class="cap-slider-row">
                                        <label>Position Y <span id="cap-ed-pos-val">75%</span></label>
                                        <input id="cap-ed-position" type="range" min="10" max="95" value="75" class="cap-range cap-range--amber">
                                    </div>
                                    <div class="cap-slider-row">
                                        <label>Letter Spacing <span id="cap-ed-ls-val">0px</span></label>
                                        <input id="cap-ed-letter-spacing" type="range" min="-5" max="20" value="0" step="1" class="cap-range cap-range--amber">
                                    </div>
                                </div>

                                <div class="cap-section-divider"></div>

                                <!-- Shadow -->
                                <div class="cap-section">
                                    <div class="cap-section-label">Shadow</div>
                                    <div class="cap-row">
                                        <label class="cap-card-field">
                                            <span>Color</span>
                                            <input id="cap-ed-shadow-color" type="color" value="#000000" class="cap-color-input">
                                        </label>
                                        <label class="cap-card-field">
                                            <span>Blur</span>
                                            <input id="cap-ed-shadow-blur" type="number" value="0" min="0" max="40" step="1" class="cap-input">
                                        </label>
                                    </div>
                                    <div class="cap-row">
                                        <label class="cap-card-field">
                                            <span>Offset X</span>
                                            <input id="cap-ed-shadow-x" type="number" value="0" min="-20" max="20" step="1" class="cap-input">
                                        </label>
                                        <label class="cap-card-field">
                                            <span>Offset Y</span>
                                            <input id="cap-ed-shadow-y" type="number" value="0" min="-20" max="20" step="1" class="cap-input">
                                        </label>
                                    </div>
                                </div>

                                <!-- Highlight -->
                                <div id="cap-highlight-section" style="display:none">
                                    <div class="cap-section-divider"></div>
                                    <div class="cap-section">
                                        <div class="cap-section-label">Highlight</div>
                                        <label class="cap-card-field">
                                            <span>Active Word Color</span>
                                            <input id="cap-ed-highlight-color" type="color" value="#4ECDC4" class="cap-color-input">
                                        </label>
                                    </div>
                                </div>

                                <div class="cap-section-divider"></div>

                                <!-- Options -->
                                <div class="cap-section">
                                    <div class="cap-section-label">Options</div>
                                    <label class="cap-option-row">
                                        <input type="checkbox" id="cap-clean-text-toggle" checked>
                                        Clean special characters except ! ? [ ]
                                    </label>
                                </div>

                            </div>


                        </div>
                    </div>
                </div>
                <div class="tab-pane" data-pane="adjustment">
                    <div class="tab-pane-body">
                        <!-- Collapsible instruction -->
                        <div class="tab-instruction">
                            <button class="tab-instruction-toggle" aria-expanded="false">
                                <svg class="tab-instruction-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                                <span class="tab-instruction-label">How it works</span>
                                <svg class="tab-instruction-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                            </button>
                            <div class="tab-instruction-body">
                                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                    <circle cx="12" cy="12" r="3"/>
                                    <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
                                </svg>
                                <p class="tab-instruction-title">Fine-tune your visuals</p>
                                <p class="tab-instruction-hint">Adjust color balance, brightness, contrast and saturation for the selected scene.</p>
                            </div>
                        </div>
                        <div class="media-empty">
                            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="1.5">
                                <circle cx="12" cy="12" r="3" />
                                <path
                                    d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
                            </svg>
                            <p>Color & brightness adjustments</p>
                        </div>
                    </div>
                </div>
            </div>
        </aside>

        <!-- Resize handle: media ↔ preview -->
        <div class="panel-resize-handle" id="resize-media" data-panel="media"></div>

        <!-- Preview Panel -->
        <section class="preview-panel" id="preview-panel">
            <div class="player-card">
                <!-- Drag handle header -->
                <div class="player-card-header" id="player-card-header">
                    <span class="player-card-title">Preview</span>
                </div>
                <!-- Video stage — height-driven, keeps 9:16 ratio -->
                <div class="preview-stage">
                    <div class="preview-container" id="preview-container">
                        <canvas id="preview-canvas" width="1080" height="1920"></canvas>
                        <div class="preview-placeholder hidden" id="preview-placeholder"></div>
                    </div>
                </div>

                <!-- Player controls bar -->
                <div class="preview-controls">
                    <input type="range" id="time-scrubber" class="time-scrubber" min="0" max="100" value="0"
                        step="0.001">
                    <div class="preview-controls-row">
                        <!-- Left group: timecode -->
                        <div class="pc-group-left">
                            <div class="time-display">
                                <span id="current-time" class="tc-current">00:00:00:00</span>
                                <span class="tc-sep">/</span>
                                <span id="total-time">00:00:00:00</span>
                            </div>
                        </div>

                        <!-- Center: skip-start, play, skip-end -->
                        <div class="pc-group-center">
                            <button id="skip-start-btn" class="pc-btn" title="Jump to Start">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" />
                                </svg>
                            </button>
                            <button id="play-btn" class="pc-play" title="Play/Pause">
                                <svg viewBox="0 0 24 24" fill="currentColor">
                                    <polygon points="6 4 20 12 6 20 6 4" />
                                </svg>
                            </button>
                            <button id="skip-end-btn" class="pc-btn" title="Jump to End">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
                                </svg>
                            </button>
                            <button id="loop-btn" class="pc-btn" title="Toggle Loop">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                    stroke-width="1.8">
                                    <polyline points="17 1 21 5 17 9" />
                                    <path d="M3 11V9a4 4 0 014-4h14" />
                                    <polyline points="7 23 3 19 7 15" />
                                    <path d="M21 13v2a4 4 0 01-4 4H3" />
                                </svg>
                            </button>
                        </div>

                        <!-- Right group: audio, ratio, fullscreen -->
                        <div class="pc-group-right">
                            <button id="volume-btn" class="pc-btn" title="Toggle Audio">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                    stroke-width="1.8">
                                    <path d="M9 18V5l12-2v13" />
                                    <circle cx="6" cy="18" r="3" />
                                    <circle cx="18" cy="16" r="3" />
                                </svg>
                            </button>
                            <div class="ratio-dropdown-container">
                                <button id="ratio-btn" class="pc-btn pc-btn-label" title="Aspect Ratio">9:16</button>
                                <div id="ratio-dropdown" class="ratio-dropdown">
                                    <div class="ratio-dropdown-header">Aspect Ratio</div>
                                    <div class="ratio-option active" data-ratio="9:16" data-w="1080" data-h="1920">
                                        <span class="ratio-label">9:16</span>
                                        <span class="ratio-icon ratio-icon-9-16"></span>
                                    </div>
                                    <div class="ratio-option" data-ratio="16:9" data-w="1920" data-h="1080">
                                        <span class="ratio-label">16:9</span>
                                        <span class="ratio-icon ratio-icon-16-9"></span>
                                    </div>
                                    <div class="ratio-option" data-ratio="4:3" data-w="1440" data-h="1080">
                                        <span class="ratio-label">4:3</span>
                                        <span class="ratio-icon ratio-icon-4-3"></span>
                                    </div>
                                    <div class="ratio-option" data-ratio="1:1" data-w="1080" data-h="1080">
                                        <span class="ratio-label">1:1</span>
                                        <span class="ratio-icon ratio-icon-1-1"></span>
                                    </div>
                                    <div class="ratio-option" data-ratio="3:4" data-w="1080" data-h="1440">
                                        <span class="ratio-label">3:4</span>
                                        <span class="ratio-icon ratio-icon-3-4"></span>
                                    </div>
                                    <div class="ratio-option" data-ratio="2.35:1" data-w="1920" data-h="817">
                                        <span class="ratio-label">2.35:1</span>
                                        <span class="ratio-icon ratio-icon-235-1"></span>
                                    </div>
                                </div>
                            </div>
                            <button id="fullscreen-btn" class="pc-btn" title="Fullscreen Preview">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                    stroke-width="1.8">
                                    <path
                                        d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m0 18h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3" />
                                </svg>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- Resize handle: preview ↔ details -->
        <div class="panel-resize-handle" id="resize-details" data-panel="details"></div>

        <!-- Detail Panel — single unified card like CapCut -->
        <aside class="properties-panel">
            <div class="detail-card">
                <div class="detail-card-header">
                    <span class="detail-card-title">Details</span>
                </div>
                <div class="detail-card-body">
                    <!-- Scene properties (dynamic) -->
                    <div id="scene-properties" class="detail-section">
                        <div class="detail-placeholder">Select a scene to edit</div>
                    </div>

                    <!-- Static project info rows -->
                    <div id="project-info" class="detail-section">
                        <div class="detail-row">
                            <span class="detail-label">Scenes</span>
                            <span class="detail-value" id="info-scenes">0</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">Duration</span>
                            <span class="detail-value" id="info-duration">0:00</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">Aspect ratio</span>
                            <span class="detail-value" id="info-ratio">9:16</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">Resolution</span>
                            <span class="detail-value" id="info-resolution">1080x1920</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">Frame rate</span>
                            <span class="detail-value">30.00fps</span>
                        </div>
                    </div>
                </div>
            </div>
        </aside>

        <!-- Timeline Panel -->
        <section class="timeline-panel">
            <div class="timeline-resize-handle" id="timeline-resize-handle"></div>

            <!-- Top toolbar: time ruler + zoom -->
            <div class="timeline-toolbar">
                <div class="toolbar-left">
                    <span class="media-status" id="media-status"></span>
                </div>
                <div class="toolbar-right">
                    <button id="select-folder" class="tl-btn" title="Select Media Folder">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2">
                            <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
                        </svg>
                    </button>
                    <button id="randomize-media" class="tl-btn" title="Randomize Scene Media">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="2" y="2" width="20" height="20" rx="3" />
                            <circle cx="8" cy="8" r="1.5" fill="currentColor" stroke="none" />
                            <circle cx="16" cy="8" r="1.5" fill="currentColor" stroke="none" />
                            <circle cx="8" cy="16" r="1.5" fill="currentColor" stroke="none" />
                            <circle cx="16" cy="16" r="1.5" fill="currentColor" stroke="none" />
                            <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
                        </svg>
                    </button>
                    <select id="randomize-media-type"
                        style="font-size: 11px; padding: 2px 4px; border-radius: 4px; background: var(--bg-darker); color: var(--text-muted); border: 1px solid var(--border); margin-left: 4px; outline: none; cursor: pointer;"
                        title="Limit randomized media type">
                        <option value="mixed">Mixed</option>
                        <option value="videos">Videos only</option>
                        <option value="images">Images only</option>
                    </select>
                    <div class="timing-adjust-group" style="display:inline-flex; align-items:center; gap:3px; background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:5px; padding:2px 5px;">
                        <button id="flip-filler-btn" class="tl-btn" title="Timing Adjust — shift scene cuts earlier/later">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="11 17 6 12 11 7" />
                                <polyline points="18 17 13 12 18 7" />
                            </svg>
                        </button>
                        <select id="flip-filler-amount"
                            style="font-size: 11px; padding: 2px 4px; border-radius: 4px; background: var(--bg-darker); color: var(--text-muted); border: 1px solid var(--border); outline: none; cursor: pointer;"
                            title="Seconds to shift each scene cut">
                            <option value="0" selected>0s</option>
                            <option value="0.25">0.25s</option>
                            <option value="0.5">0.5s</option>
                            <option value="0.75">0.75s</option>
                            <option value="1">1s</option>
                            <option value="1.5">1.5s</option>
                            <option value="2">2s</option>
                            <option value="2.5">2.5s</option>
                            <option value="3">3s</option>
                            <option value="3.5">3.5s</option>
                        </select>
                        <label style="display:flex; align-items:center; gap:3px; font-size:10px; color:var(--text-muted); cursor:pointer;" title="Randomly vary each scene earlier or later">
                            <input type="checkbox" id="flip-filler-random"
                                style="width:12px; height:12px; accent-color:var(--accent); cursor:pointer;">
                            <span>Rnd&plusmn;</span>
                        </label>
                    </div>
                    <div class="zoom-controls">
                        <button id="zoom-out" class="tl-btn" title="Zoom Out">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2">
                                <circle cx="11" cy="11" r="7" />
                                <path d="M21 21l-4-4" />
                                <path d="M8 11h6" />
                            </svg>
                        </button>
                        <span class="zoom-level" id="zoom-level">100%</span>
                        <button id="zoom-in" class="tl-btn" title="Zoom In">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2">
                                <circle cx="11" cy="11" r="7" />
                                <path d="M21 21l-4-4" />
                                <path d="M11 8v6M8 11h6" />
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="timeline-header-marker" id="timeline-header-marker">
                    <div class="header-marker-track"></div>
                    <div class="header-marker-trail"></div>
                    <div class="header-marker-indicator"></div>
                </div>
            </div>

            <!-- Timeline Minimap (overview bar) -->
            <div class="timeline-minimap" id="timeline-minimap"></div>

            <!-- Time Ruler (top, above tracks) -->
            <div class="time-ruler" id="time-ruler"></div>

            <!-- Playhead -->
            <div class="timeline-playhead" id="timeline-playhead">
                <div class="playhead-time-label" id="playhead-time-label"></div>
                <div class="playhead-marker"></div>
                <div class="playhead-line"></div>
            </div>

            <!-- Timeline Tracks -->
            <div class="timeline-tracks" id="timeline-tracks">
                <!-- Video Track -->
                <div class="track" data-track="video">
                    <div class="track-header">
                        <svg class="track-toggle" title="Toggle Video Track" width="13" height="13" viewBox="0 0 24 24"
                            fill="none" stroke="currentColor" stroke-width="1.8">
                            <rect x="2" y="3" width="20" height="18" rx="2" />
                            <path d="M7 3v18" />
                            <path d="M17 3v18" />
                            <path d="M2 7.5h5" />
                            <path d="M2 12h5" />
                            <path d="M2 16.5h5" />
                            <path d="M17 7.5h5" />
                            <path d="M17 12h5" />
                            <path d="M17 16.5h5" />
                        </svg>
                        <span class="track-label">Video</span>
                        <button class="video-audio-toggle muted" id="video-audio-toggle" title="Video Audio (muted)">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                                <line class="video-audio-x1" x1="23" y1="9" x2="17" y2="15"/>
                                <line class="video-audio-x2" x1="17" y1="9" x2="23" y2="15"/>
                            </svg>
                        </button>
                    </div>
                    <div class="track-content" id="video-track"></div>
                </div>

                <!-- Text Track -->
                <div class="track" data-track="text">
                    <div class="track-header">
                        <svg class="track-toggle" title="Toggle Text Track" width="13" height="13" viewBox="0 0 24 24"
                            fill="none" stroke="currentColor" stroke-width="1.8">
                            <path d="M4 7V4h16v3" />
                            <path d="M12 4v16" />
                            <path d="M8 20h8" />
                        </svg>
                        <span class="track-label">Text</span>
                    </div>
                    <div class="track-content" id="text-track"></div>
                </div>

                <!-- Caption Track (hidden until enabled) -->
                <div class="track" data-track="caption" id="caption-track-row" style="display:none">
                    <div class="track-header">
                        <svg class="track-toggle" title="Toggle Caption Track" width="13" height="13"
                            viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                            <rect x="2" y="4" width="20" height="16" rx="2" />
                            <path d="M6 14h4" />
                            <path d="M14 14h4" />
                            <path d="M6 18h12" />
                        </svg>
                        <span class="track-label">Cap</span>
                    </div>
                    <div class="track-content" id="caption-track"></div>
                </div>

                <!-- Dynamic Audio Tracks -->
                <div id="audio-tracks-container">
                    <!-- Audio tracks rendered dynamically by JS -->
                </div>
                <div class="add-track-row" id="add-track-row">
                    <div class="add-track-header">
                        <button id="add-audio-track-btn" class="add-track-btn" title="Add Audio Track">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2.5" stroke-linecap="round">
                                <path d="M12 5v14M5 12h14" />
                            </svg>
                        </button>
                    </div>
                    <div class="add-track-content">
                        <span class="add-track-label">Add audio track</span>
                    </div>
                </div>
            </div>
        </section>
    </div>

    <!-- Dialogs rendered by EditorPage.vue as Vue-managed siblings -->

    <!-- video-editor.js loaded as module from static/js/editor/ -->
`;

// All dialogs migrated to Vue components — see editor/components/
// MusicPickerDialog, ShareDialog, NoDataOverlay, AssetPickerDialog,
// TTSPickerDialog, ResetConfirmModal, ExportJsonModal, ExportProgressModal
