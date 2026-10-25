import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{allowedHosts:['terminal.local'],proxy:{'/api/inventory':{target:process.env.INVENTORY_URL||'http://localhost:8081'},'/api/workshop':{target:process.env.WORKSHOP_URL||'http://localhost:8082'},'/api/vision':{target:process.env.VISION_URL||'http://localhost:8083'}}},build:{sourcemap:false}});
