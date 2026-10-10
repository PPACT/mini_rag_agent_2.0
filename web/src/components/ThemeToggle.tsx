import { Moon, Sun } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { setTheme, useTheme } from '@/lib/theme'

export function ThemeToggle() {
  const theme = useTheme()
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={theme === 'dark' ? '切到浅色' : '切到深色'}
      title={theme === 'dark' ? '切到浅色' : '切到深色'}
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
    >
      {theme === 'dark' ? <Sun /> : <Moon />}
    </Button>
  )
}
