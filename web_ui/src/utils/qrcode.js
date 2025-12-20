/** 二维码生成工具 */

import QRCode from 'qrcode'

/**
 * 生成二维码 SVG
 * @param {string} data - 要编码的数据
 * @returns {Promise<string>} SVG 字符串
 */
export async function generateQRCodeSVG(data) {
  try {
    const svg = await QRCode.toString(data, {
      type: 'svg',
      width: 300,
      margin: 2
    })
    return svg
  } catch (error) {
    console.error('生成二维码失败:', error)
    throw error
  }
}

/**
 * 生成二维码 Data URL
 * @param {string} data - 要编码的数据
 * @returns {Promise<string>} Data URL
 */
export async function generateQRCodeDataURL(data) {
  try {
    const dataUrl = await QRCode.toDataURL(data, {
      width: 300,
      margin: 2
    })
    return dataUrl
  } catch (error) {
    console.error('生成二维码失败:', error)
    throw error
  }
}

