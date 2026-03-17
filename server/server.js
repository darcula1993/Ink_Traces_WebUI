import express from 'express'
import cors from 'cors'
import dotenv from 'dotenv'
import multer from 'multer'
import { GoogleGenAI } from '@google/genai'
import fs from 'fs'

dotenv.config()

process.env.GOOGLE_GENAI_USE_VERTEXAI = 'True'
process.env.GOOGLE_CLOUD_PROJECT = process.env.GOOGLE_CLOUD_PROJECT || 'GOOGLE_CLOUD_PROJECT'
process.env.GOOGLE_CLOUD_LOCATION = process.env.GOOGLE_CLOUD_LOCATION || 'global'

const app = express()
const PORT = process.env.PORT || 5000

app.use(cors())
app.use(express.json({ limit: '50mb' }))
app.use(express.urlencoded({ extended: true, limit: '50mb' }))

const upload = multer({ dest: 'uploads/' })

const client = new GoogleGenAI({
  apiKey: process.env.API_KEY
})

const MODEL_ID = process.env.MODEL_ID || 'gemini-3-pro-image-preview'

app.post('/api/generate/text-to-image', async (req, res) => {
  try {
    const { prompt, aspect_ratio = '9:16', resolution = '2K' } = req.body

    if (!prompt) {
      return res.status(400).json({
        success: false,
        error: '请提供图片描述'
      })
    }

    console.log('Generating image with prompt:', prompt)

    const response = await client.models.generateContent({
      model: MODEL_ID,
      contents: [prompt],
      config: {
        responseModalities: ['TEXT', 'IMAGE'],
        imageConfig: {
          aspectRatio: aspect_ratio,
          imageSize: resolution
        }
      }
    })

    let thinking = ''
    let imageBase64 = null

    if (response.candidates && response.candidates[0] && response.candidates[0].content) {
      for (const part of response.candidates[0].content.parts) {
        if (part.text) {
          thinking = part.text
          console.log('AI thinking:', thinking)
        } else if (part.inlineData) {
          const buffer = typeof part.inlineData.data === 'string'
            ? Buffer.from(part.inlineData.data, 'base64')
            : Buffer.from(part.inlineData.data)
          imageBase64 = `data:${part.inlineData.mimeType};base64,${buffer.toString('base64')}`
        }
      }
    }

    if (!imageBase64) {
      return res.status(500).json({
        success: false,
        error: '未能生成图片'
      })
    }

    res.json({
      success: true,
      image: imageBase64,
      thinking
    })

  } catch (error) {
    console.error('Error generating image:', error)
    res.status(500).json({
      success: false,
      error: error.message || '生成图片时出错'
    })
  }
})

app.post('/api/generate/image-to-image', upload.single('image'), async (req, res) => {
  try {
    const { prompt, aspect_ratio = '3:4', resolution = '2K' } = req.body
    const imageFile = req.file

    if (!prompt) {
      return res.status(400).json({
        success: false,
        error: '请提供修改描述'
      })
    }

    if (!imageFile) {
      return res.status(400).json({
        success: false,
        error: '请上传参考图片'
      })
    }

    console.log('Generating image with prompt:', prompt)
    console.log('Reference image:', imageFile.originalname)

    const imageBuffer = fs.readFileSync(imageFile.path)
    const imageBase64 = imageBuffer.toString('base64')

    const response = await client.models.generateContent({
      model: MODEL_ID,
      contents: [
        prompt,
        {
          inlineData: {
            mimeType: imageFile.mimetype,
            data: imageBase64
          }
        }
      ],
      config: {
        responseModalities: ['TEXT', 'IMAGE'],
        imageConfig: {
          aspectRatio: aspect_ratio,
          imageSize: resolution
        }
      }
    })

    fs.unlinkSync(imageFile.path)

    let thinking = ''
    let generatedImageBase64 = null

    if (response.candidates && response.candidates[0] && response.candidates[0].content) {
      for (const part of response.candidates[0].content.parts) {
        if (part.text) {
          thinking = part.text
          console.log('AI thinking:', thinking)
        } else if (part.inlineData) {
          const buffer = typeof part.inlineData.data === 'string'
            ? Buffer.from(part.inlineData.data, 'base64')
            : Buffer.from(part.inlineData.data)
          generatedImageBase64 = `data:${part.inlineData.mimeType};base64,${buffer.toString('base64')}`
        }
      }
    }

    if (!generatedImageBase64) {
      return res.status(500).json({
        success: false,
        error: '未能生成图片'
      })
    }

    res.json({
      success: true,
      image: generatedImageBase64,
      thinking
    })

  } catch (error) {
    console.error('Error generating image:', error)

    if (req.file && fs.existsSync(req.file.path)) {
      fs.unlinkSync(req.file.path)
    }

    res.status(500).json({
      success: false,
      error: error.message || '生成图片时出错'
    })
  }
})

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', message: 'Server is running' })
})

if (!fs.existsSync('uploads')) {
  fs.mkdirSync('uploads')
}

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Server is running on http://0.0.0.0:${PORT}`)
})
