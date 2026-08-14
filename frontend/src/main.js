import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'

import App from './App.vue'
import ChannelsPage from './features/channels/ChannelsPage.vue'
import ChannelEditor from './features/channels/ChannelEditor.vue'
import { APP_NAME } from './shared/constants.js'

const Home = {
  template: `
    <section style="max-width:720px;margin:0 auto;padding:2rem 1.25rem;font-family:system-ui,sans-serif;color:#e8eaed">
      <h1 style="margin:0 0 .5rem;font-size:1.75rem">{{ name }}</h1>
      <p style="color:#9aa0a6;line-height:1.5">
        Channel-aware, provider-driven, local-first AI video production.
        Production and Workflow views land in Phase 2.
      </p>
      <p style="margin-top:1.25rem">
        <router-link to="/channels" style="color:#8ab4f8">Open Channels →</router-link>
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
    { path: '/channels', name: 'channels', component: ChannelsPage },
    { path: '/channels/:id', name: 'channel-edit', component: ChannelEditor },
  ],
})

createApp(App).use(router).mount('#app')
