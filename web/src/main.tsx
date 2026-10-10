import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.tsx'
import { TooltipProvider } from '@/components/ui/tooltip'
import './index.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root 不存在 —— index.html 被改过？')

createRoot(root).render(
  <StrictMode>
    <TooltipProvider>
      <App />
    </TooltipProvider>
  </StrictMode>,
)
