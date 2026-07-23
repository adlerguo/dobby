<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <section class="page forbidden-page">
    <el-result
      icon="warning"
      title="无权访问"
      sub-title="当前账号没有访问该页面所需的权限，请联系管理员调整角色。"
    >
      <template #extra>
        <el-button type="primary" @click="router.push('/dashboard')">返回工作台</el-button>
        <el-button @click="router.push('/login')">切换账号</el-button>
      </template>
    </el-result>
  </section>
</template>

<style scoped>
.forbidden-page {
  min-height: 60vh;
  display: grid;
  place-items: center;
}
</style>
