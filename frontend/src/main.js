import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'

import App from './App.vue'
import ChannelsPage from './features/channels/ChannelsPage.vue'
import ChannelEditor from './features/channels/ChannelEditor.vue'
import ProductionPage from './features/production/ProductionPage.vue'
import ProvidersSettingsPage from './features/providers/ProvidersSettingsPage.vue'
import { APP_NAME } from './shared/constants.js'

import './styles/theme.css'
import './styles/shared.css'

const Home = {
  template: `
    <section style="max-width:720px;margin:0 auto;padding:2rem 1.25rem;font-family:var(--font-body,system-ui),sans-serif;color:var(--text,#e8eaed)">
      <h1 style="margin:0 0 .5rem;font-size:1.75rem;font-family:var(--font-display,system-ui)">{{ name }}</h1>
      <p style="color:var(--text-secondary,#9aa0a6);line-height:1.5">
        Channel-aware, provider-driven, local-first AI video production.
        Production and Workflow views share one node-based execution.
      </p>
      <p style="margin-top:1.25rem;display:flex;gap:1.25rem;flex-wrap:wrap">
        <router-link to="/production" style="color:var(--accent,#8ab4f8)">Open Production →</router-link>
        <router-link to="/workflow" style="color:var(--accent,#8ab4f8)">Open Workflow →</router-link>
        <router-link to="/channels" style="color:var(--accent,#8ab4f8)">Open Channels →</router-link>
      </p>
    </section>
  `,
  setup() {
    return { name: APP_NAME }
  },
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Home },
    {
      path: '/production',
      name: 'production',
      component: ProductionPage,
      meta: { title: 'Production' },
    },
    {
      path: '/workflow',
      name: 'workflow',
      component: () => import('./features/workflow/views/WorkflowPage.vue'),
      meta: { title: 'Workflow Builder', fullHeight: true },
    },
    {
      // Lazy on purpose. The ported editor pulls in a 139 KB global
      // stylesheet whose generic class names (.modal-*, .btn-secondary,
      // .toggle-slider) would otherwise bleed into every other view.
      path: '/editor',
      name: 'editor',
      component: () => import('./features/editor/views/EditorPage.vue'),
      meta: { title: 'Timeline Editor', fullHeight: true },
    },
    { path: '/channels', name: 'channels', component: ChannelsPage },
    { path: '/channels/:id', name: 'channel-edit', component: ChannelEditor },
    {
      path: '/settings/providers',
      name: 'provider-settings',
      component: ProvidersSettingsPage,
      meta: { title: 'Provider Settings' },
    },
  ],
  linkActiveClass: 'router-link-active',
  linkExactActiveClass: 'router-link-active',
})

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
