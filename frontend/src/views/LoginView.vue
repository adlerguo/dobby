<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const form = ref({
  tenant_code: 'default',
  username: 'admin',
  password: 'Admin123!',
})
const loading = ref(false)
const errorMessage = ref('')

function fillDemoAccount() {
  form.value = {
    tenant_code: 'default',
    username: 'admin',
    password: 'Admin123!',
  }
  errorMessage.value = ''
}

async function submit() {
  loading.value = true
  errorMessage.value = ''
  try {
    await auth.login(form.value)
    router.push('/dashboard')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card">
      <div class="login-brand">
        <div class="brand-mark">AI</div>
        <div>
          <h1>登录企业智能体中台</h1>
          <p>使用租户账号进入工作台。</p>
        </div>
      </div>

      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

      <el-form class="login-form" label-position="top" @keyup.enter="submit">
        <el-form-item label="租户编码">
          <el-input v-model="form.tenant_code" autocomplete="organization" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" autocomplete="current-password" show-password />
        </el-form-item>
        <el-button class="login-submit" type="primary" :loading="loading" @click="submit">继续</el-button>
        <el-button text class="demo-button" @click="fillDemoAccount">填入演示账号</el-button>
      </el-form>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  display: grid;
  min-height: 100vh;
  place-items: center;
  background: #f4f6f8;
  padding: 24px;
}

.login-card {
  width: min(100%, 420px);
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #ffffff;
  padding: 28px;
  box-shadow: 0 18px 50px rgba(20, 61, 89, 0.12);
}

.login-brand {
  display: grid;
  justify-items: center;
  gap: 12px;
  margin-bottom: 24px;
  text-align: center;
}

.login-brand h1 {
  margin: 0;
  font-size: 24px;
}

.login-brand p {
  margin: 6px 0 0;
  color: #667085;
}

.login-form {
  margin-top: 16px;
}

.login-submit,
.demo-button {
  width: 100%;
}

.demo-button {
  margin: 8px 0 0;
}
</style>
