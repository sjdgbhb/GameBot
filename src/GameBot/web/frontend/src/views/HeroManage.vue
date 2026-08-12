<script setup lang="ts">
import { useHeroStore } from '@/stores/hero'
import HeroesGallery from '@/components/hero/HeroesGallery.vue'

const heroStore = useHeroStore()

const emit = defineEmits<{
  refresh: []
}>()
</script>

<template>
  <HeroesGallery
    :heroes="heroStore.heroes"
    :items="heroStore.items"
    @refresh="emit('refresh')"
  />
</template>
