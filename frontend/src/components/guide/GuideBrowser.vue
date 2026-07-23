<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { marked } from 'marked'
import { Search } from 'lucide-vue-next'

import EmptyState from '../common/EmptyState.vue'

interface GuideArticle {
  slug: string
  title: string
  category: string
  order: number
  updatedAt: string
  body: string
  plainText: string
  html: string
}

const props = withDefaults(
  defineProps<{
    embedded?: boolean
  }>(),
  {
    embedded: false,
  }
)

const keyword = ref('')
const openCategories = ref<string[]>([])
const selectedSlug = ref('')
const categoryOrder = ['产品介绍', '快速开始', '模型接入', '知识库', '智能体', '工具中心', '发布上线', '观测运维', '平台管理', '常见问题']
const rawModules = import.meta.glob('/src/guide/**/*.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
const articles = buildArticles(rawModules)
const linearArticles = computed(() => [...articles].sort(articleSort))
const categories = computed(() => {
  const grouped = new Map<string, GuideArticle[]>()
  for (const article of linearArticles.value) {
    if (!grouped.has(article.category)) grouped.set(article.category, [])
    grouped.get(article.category)?.push(article)
  }
  return Array.from(grouped.entries()).map(([category, items]) => ({ category, items }))
})
const currentArticle = computed(() => linearArticles.value.find((article) => article.slug === selectedSlug.value) || linearArticles.value[0])
const currentIndex = computed(() => linearArticles.value.findIndex((article) => article.slug === currentArticle.value?.slug))
const prevArticle = computed(() => (currentIndex.value > 0 ? linearArticles.value[currentIndex.value - 1] : null))
const nextArticle = computed(() => (currentIndex.value >= 0 && currentIndex.value < linearArticles.value.length - 1 ? linearArticles.value[currentIndex.value + 1] : null))
const searchResults = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  if (!query) return []
  return linearArticles.value.filter((article) => `${article.title}\n${article.plainText}`.toLowerCase().includes(query))
})

watch(
  currentArticle,
  (article) => {
    if (!article) return
    selectedSlug.value = article.slug
    if (!openCategories.value.includes(article.category)) {
      openCategories.value = [...openCategories.value, article.category]
    }
  },
  { immediate: true }
)

function buildArticles(modules: Record<string, string>) {
  return Object.entries(modules).filter(([path]) => isGuideMarkdownPath(path)).map(([path, raw]) => {
    const { meta, body } = parseFrontmatter(raw)
    const slug = path.replace(/^\/src\/guide\//, '').replace(/\.md$/, '')
    const plainText = stripMarkdown(body)
    return {
      slug,
      title: meta.title || slug.split('/').pop() || '未命名教程',
      category: meta.category || '使用教程',
      order: Number(meta.order || 999),
      updatedAt: meta.updated_at || '',
      body,
      plainText,
      html: sanitizeHtml(marked.parse(body, { async: false }) as string),
    }
  })
}

function parseFrontmatter(raw: string) {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/)
  if (!match) return { meta: {} as Record<string, string>, body: raw }
  const meta: Record<string, string> = {}
  for (const line of match[1].split(/\r?\n/)) {
    const item = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*$/)
    if (!item) continue
    const key = item[1]
    if (['title', 'category', 'order', 'updated_at'].includes(key)) {
      meta[key] = item[2].replace(/^['"]|['"]$/g, '')
    }
  }
  return { meta, body: match[2].trim() }
}

function isGuideMarkdownPath(path: string) {
  const fileName = path.split('/').pop() || ''
  return path.endsWith('.md') && !fileName.startsWith('.') && !path.includes('__MACOSX') && !path.includes('.DS_Store')
}

function stripMarkdown(markdown: string) {
  return markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#>*_`[\]()~-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function sanitizeHtml(html: string) {
  return html
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?>[\s\S]*?<\/style>/gi, '')
    .replace(/\son\w+="[^"]*"/gi, '')
    .replace(/\son\w+='[^']*'/gi, '')
    .replace(/href=["']javascript:[^"']*["']/gi, 'href="#"')
}

function articleSort(a: GuideArticle, b: GuideArticle) {
  const categoryDelta = categoryOrder.indexOf(a.category) - categoryOrder.indexOf(b.category)
  if (categoryDelta !== 0) return categoryDelta
  return a.order - b.order || a.title.localeCompare(b.title, 'zh-Hans-CN')
}

function selectArticle(article: GuideArticle) {
  selectedSlug.value = article.slug
  keyword.value = ''
}
</script>

<template>
  <section class="guide-browser" :class="{ embedded }">
    <header v-if="!embedded" class="guide-hero">
      <div>
        <h1>使用教程</h1>
        <p>从模型接入、知识库、智能体创建到发布上线，按步骤了解平台完整使用方式。</p>
      </div>
      <el-input v-model="keyword" class="guide-search" size="large" placeholder="搜索教程关键词">
        <template #prefix>
          <Search :size="18" />
        </template>
      </el-input>
    </header>

    <div v-else class="embedded-search">
      <el-input v-model="keyword" placeholder="搜索教程关键词">
        <template #prefix>
          <Search :size="18" />
        </template>
      </el-input>
    </div>

    <div class="guide-layout">
      <aside class="guide-sidebar">
        <el-collapse v-model="openCategories">
          <el-collapse-item v-for="group in categories" :key="group.category" :title="group.category" :name="group.category">
            <button
              v-for="article in group.items"
              :key="article.slug"
              class="guide-nav-item"
              :class="{ active: currentArticle?.slug === article.slug }"
              type="button"
              @click="selectArticle(article)"
            >
              {{ article.title }}
            </button>
          </el-collapse-item>
        </el-collapse>
      </aside>

      <main class="guide-main">
        <section v-if="keyword.trim()" class="panel-card guide-search-results">
          <strong>搜索结果</strong>
          <EmptyState
            v-if="searchResults.length === 0"
            title="没有找到相关教程"
            description="请尝试使用模型、知识库、智能体、发布等关键词重新搜索。"
          />
          <button v-for="article in searchResults" :key="article.slug" type="button" @click="selectArticle(article)">
            <span>{{ article.category }}</span>
            <strong>{{ article.title }}</strong>
          </button>
        </section>

        <article v-if="currentArticle" class="panel-card guide-article">
          <el-breadcrumb v-if="!embedded" separator="/">
            <el-breadcrumb-item>使用教程</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentArticle.category }}</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentArticle.title }}</el-breadcrumb-item>
          </el-breadcrumb>
          <header>
            <h2>{{ currentArticle.title }}</h2>
            <span>更新时间：{{ currentArticle.updatedAt }}</span>
          </header>
          <div class="guide-markdown" v-html="currentArticle.html" />
        </article>

        <nav class="guide-pager">
          <button v-if="prevArticle" class="panel-card" type="button" @click="selectArticle(prevArticle)">
            <span>上一篇</span>
            <strong>{{ prevArticle.title }}</strong>
          </button>
          <span v-else />
          <button v-if="nextArticle" class="panel-card next" type="button" @click="selectArticle(nextArticle)">
            <span>下一篇</span>
            <strong>{{ nextArticle.title }}</strong>
          </button>
        </nav>
      </main>
    </div>
  </section>
</template>

<style scoped>
.guide-browser {
  display: grid;
  gap: var(--space-5);
}

.guide-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
  align-items: center;
  gap: var(--space-5);
}

.guide-hero h1 {
  margin: 0 0 var(--space-2);
  color: var(--color-text-primary);
  font-size: 28px;
}

.guide-hero p {
  margin: 0;
  color: var(--color-text-secondary);
}

.guide-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}

.guide-browser.embedded {
  gap: var(--space-3);
}

.guide-browser.embedded .guide-layout {
  grid-template-columns: 200px minmax(0, 1fr);
  gap: var(--space-4);
}

.embedded-search {
  max-width: 420px;
}

.guide-sidebar {
  position: sticky;
  top: var(--space-5);
  max-height: calc(100vh - 160px);
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  padding: var(--space-3);
}

.guide-browser.embedded .guide-sidebar {
  position: static;
  max-height: 680px;
}

.guide-nav-item {
  display: block;
  width: 100%;
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-secondary);
  cursor: pointer;
  text-align: left;
}

.guide-nav-item:hover,
.guide-nav-item.active {
  background: #eef4ff;
  color: #1d4ed8;
}

.guide-main {
  display: grid;
  gap: var(--space-4);
  min-width: 0;
}

.guide-search-results {
  display: grid;
  gap: var(--space-3);
}

.guide-search-results button {
  display: grid;
  gap: 4px;
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  background: #ffffff;
  padding: var(--space-3);
  cursor: pointer;
  text-align: left;
}

.guide-search-results button span,
.guide-pager span,
.guide-article header span {
  color: var(--color-text-muted);
  font-size: 13px;
}

.guide-article {
  display: grid;
  gap: var(--space-4);
}

.guide-article header h2 {
  margin: 0 0 var(--space-2);
  color: var(--color-text-primary);
  font-size: 30px;
}

.guide-browser.embedded .guide-article header h2 {
  font-size: 24px;
}

.guide-markdown {
  color: var(--color-text-primary);
  line-height: 1.85;
}

.guide-markdown :deep(h1),
.guide-markdown :deep(h2),
.guide-markdown :deep(h3) {
  margin: var(--space-5) 0 var(--space-3);
}

.guide-markdown :deep(p) {
  margin: 0 0 var(--space-4);
}

.guide-markdown :deep(ul),
.guide-markdown :deep(ol) {
  padding-left: 1.4em;
}

.guide-markdown :deep(code) {
  border-radius: var(--radius-sm);
  background: var(--color-bg-subtle);
  padding: 2px 6px;
}

.guide-pager {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.guide-pager button {
  display: grid;
  gap: var(--space-1);
  border: 1px solid var(--color-border-subtle);
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.guide-pager .next {
  text-align: right;
}

@media (max-width: 1100px) {
  .guide-hero,
  .guide-layout,
  .guide-browser.embedded .guide-layout {
    grid-template-columns: 1fr;
  }

  .guide-sidebar {
    position: static;
    max-height: none;
  }
}

@media (max-width: 720px) {
  .guide-pager {
    grid-template-columns: 1fr;
  }

  .guide-pager .next {
    text-align: left;
  }
}
</style>
