/**
 * The six destinations, in the prototype's order: create, run, monitor,
 * output, configure (step 1.1).
 *
 * Routes live here rather than in `main.js` so the redirect table is testable
 * without mounting the app — "every previous route redirects rather than
 * returning a 404" is an assertion about this array, not about the shell.
 */
import { createRouter, createWebHistory } from 'vue-router'

import ChannelsPage from './features/channels/ChannelsPage.vue'
import ChannelEditor from './features/channels/ChannelEditor.vue'
import ProductionPage from './features/production/ProductionPage.vue'
import ProvidersSettingsPage from './features/providers/ProvidersSettingsPage.vue'
import ScriptPage from './features/script/ScriptPage.vue'
import SchemaPage from './features/schema/SchemaPage.vue'
import { APP_NAME } from './shared/constants.js'

const Home = {
  template: `
    <section style="max-width:720px;margin:0 auto;padding:2rem 1.25rem;font-family:var(--body);color:var(--text)">
      <h1 class="page-title" style="font-size:28px">{{ name }}</h1>
      <p class="page-subtitle" style="font-size:13.5px">
        Channel-aware, provider-driven, local-first AI video production.
        Production and Schema are projections of one node-based execution.
      </p>
      <p style="margin-top:1.5rem;display:flex;gap:.6rem;flex-wrap:wrap">
        <router-link class="btn primary" to="/production">Open Production →</router-link>
        <router-link class="btn" to="/script">Open Script →</router-link>
        <router-link class="btn" to="/channels">Open Channels →</router-link>
      </p>
    </section>
  `,
  setup() {
    return { name: APP_NAME }
  },
}

export const routes = [
  { path: '/', name: 'home', component: Home },

  // ---- The six destinations -------------------------------------------
  {
    path: '/script',
    name: 'script',
    component: ScriptPage,
    meta: { title: 'Script' },
  },
  {
    path: '/production',
    name: 'production',
    component: ProductionPage,
    meta: { title: 'Production' },
  },
  {
    path: '/schema',
    name: 'schema',
    component: SchemaPage,
    // The canvas fills the shell rather than scrolling inside it (step 1.2).
    meta: { title: 'Schema', fullHeight: true },
  },
  {
    path: '/library',
    name: 'library',
    component: () => import('./features/export-library/views/ExportLibraryPage.vue'),
    meta: { title: 'Library' },
  },
  { path: '/channels', name: 'channels', component: ChannelsPage },
  { path: '/channels/:id', name: 'channel-edit', component: ChannelEditor },
  {
    path: '/providers',
    name: 'providers',
    component: ProvidersSettingsPage,
    meta: { title: 'Providers' },
  },

  // ---- Reachable, but not destinations --------------------------------
  {
    // Lazy on purpose. The ported editor pulls in a 139 KB global
    // stylesheet whose generic class names (.modal-*, .btn-secondary,
    // .toggle-slider) would otherwise bleed into every other view.
    path: '/editor',
    name: 'editor',
    component: () => import('./features/editor/views/EditorPage.vue'),
    meta: { title: 'Timeline Editor', fullHeight: true },
  },

  // ---- Redirects from every previous path ------------------------------
  // The query is the whole instruction for these pages (`?project=…`), so a
  // bare string redirect would silently drop the deep link it was built for.
  { path: '/exports', redirect: (to) => ({ name: 'library', query: to.query }) },
  { path: '/settings/providers', redirect: (to) => ({ name: 'providers', query: to.query }) },
]

export function createAppRouter(history = createWebHistory()) {
  return createRouter({
    history,
    routes,
    linkActiveClass: 'router-link-active',
    linkExactActiveClass: 'router-link-active',
  })
}
