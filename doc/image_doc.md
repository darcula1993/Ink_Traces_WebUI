`POST https://ark.ap-southeast.bytepluses.com/api/v3/images/generations` [Try](<https://api.byteplus.com/api-explorer/?action=ImageGenerations&groupName=Image%20Generation%20API&serviceCode=ark&version=2024-01-01>)

This document describes the input and output parameters for the image generation API.

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>

<div data-tips="true" data-tips-type="tip">This API is supported in both the <code>ap-southeast-1</code> and <code>eu-west-1</code> regions. Use the corresponding Base URL when making requests to endpoints in different regions.</div>

<div data-tips="true" data-tips-type="tip">Base URL by region:</div>

* <div data-tips="true" data-tips-type="tip">ap\-southeast\-1: https://ark.ap\-southeast.bytepluses.com/api/v3</div>
* <div data-tips="true" data-tips-type="tip">eu\-west\-1: https://ark.eu\-west.bytepluses.com/api/v3</div>

  <div data-tips="true" data-tips-type="tip">For more information about the available regions, see <a href="https://docs.byteplus.com/en/docs/ModelArk/2191806">Region availability</a>.   </div>

**Image** **generation capabilities by model**

* **seedream\-5\-0\-pro** **<mark></mark><sup>new</mark>**

  * Generate a single image. **sequential_image_generation** is not supported.

    * Generate a single image from **<ins>multiple reference images (210)</ins>** <ins> + text prompt</ins>.
    * Generate a single image from <ins>a single reference image + text prompt</ins>.
    * Generate a single image from <ins>text prompt</ins>.
  * `stream` and `sequential_image_generation` are not supported.
* **seedream\-5\-0\-lite** , **seedream\-4\-5/4\-0**

  * Generate multiple image in sequence \- i.e., a batch of related images generated based on your input; set **sequential_image_generation** to `auto`

    * Generate a batch of related images based on your input of **<ins>multiple reference images (214) +</ins>**  <ins>text prompt</ins> (the total number of input and output images ≤ 15).
    * Generate a batch of related images (up to 14) from a <ins>single reference image + text prompt</ins>.
    * Generate a batch of related images (up to 15) from text <ins>prompt</ins>.
  * Generate a single image (set **sequential_image_generation** to `disabled`).

    * Generate a single image from **<ins>multiple reference images (214)</ins>** <ins> + text prompt</ins>.
    * Generate a single image from <ins>a single reference image + text prompt</ins>.
    * Generate a single image from <ins>text prompt</ins>.
* **seedream\-3\-0\-t2i**

  * Generate a single image from <ins>a text prompt</ins>.

&nbsp;

<Tabs>
<Tab zoneid="VEORAzEP8i" title="Quick start">
<TabTitle>Quick start</TabTitle>

<span> </span> [Experience Center](https://console.byteplus.com/ark/region:ark+ap-southeast-1/experience/vision?type=GenImage) <span> </span> [Model List](https://docs.byteplus.com/en/docs/ModelArk/1330310#d3e5e0eb) <span> </span> [Model Billing](https://docs.byteplus.com/en/docs/ModelArk/1099320#image-generation) <span> </span> [API Key](https://console.byteplus.com/ark/region:ark+ap-southeast-1/apiKey?apikey=%7B%7D)

<span> </span> [API Call Guide](https://docs.byteplus.com/en/docs/ModelArk/1824690) <span> </span> [API Reference](https://docs.byteplus.com/en/docs/ModelArk/1666945) <span> </span> [FAQs](https://docs.byteplus.com/en/docs/ModelArk/1359411) <span> </span> [Model Activation](https://console.byteplus.com/ark/region:ark+ap-southeast-1/openManagement?LLM=%7B%7D&OpenTokenDrawer=false)

</Tab>
<Tab zoneid="ZMmz0q1YhF" title="Authentication">
<TabTitle>Authentication</TabTitle>

This API only supports API Key authentication. Obtain a long\-term API Key on the [API Key management](https://console.byteplus.com/ark/region:ark+ap-southeast-1/apiKey?apikey=%7B%7D) page.

</Tab>
</Tabs>

---

<span id="7thx2dVa"></span>

## Request parameters

<span id="BFVUvDi6"></span>

### Request body

---

**model** `string` `Required`

The model ID used for image generation: [Model ID](https://docs.byteplus.com/en/docs/ModelArk/1330310#d3e5e0eb) or [inference endpoint](https://docs.byteplus.com/en/docs/ModelArk/1099522) (Endpoint ID).

---

**prompt** `string` `Required`

The text prompt used for image generation. (Prompt guide: [Seedream 4.0-4.5](https://docs.byteplus.com/en/docs/ModelArk/1829186), [Seedream 3.0](https://docs.byteplus.com/en/docs/ModelArk/1795150))

We recommend keeping the prompt under **600 English words** . Excessively long prompts may scatter information, causing the model to overlook details and focus only on major elements, which can result in missing details in the generated image.

---

**image** `string/array`

> seedream\-3\-0\-t2i does not support this parameter.

Provide the image to edit as a Base64 string or an accessible URL. **seedream\-5\-0\-pro, 5\-0\-lite, 4\-5 and 4\-0** support inputting a single image or multiple images ([see the multi-image blending example](https://docs.byteplus.com/en/docs/ModelArk/1824121#multi-image-blending-multi-image-input-single-image-output)).

* Image URL: Ensure that the image URL is accessible.
* Base64 encoding: The format must be `data:image/<image format>;base64,<Base64 encoding>`. Note that `<image format>` must be in lowercase, e.g., `data:image/png;base64,<base64_image>`.

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>

* <div data-tips="true" data-tips-type="tip">Input Images must meet the following requirements:</div>

  * <div data-tips="true" data-tips-type="tip">Image format: jpeg, png (The seedream\-5\-0\-pro, 5\-0\-lite, 4\-5 and 4\-0 models also support webp, bmp, tiff, gif, heic and heif formats)</div>
  * <div data-tips="true" data-tips-type="tip">Aspect ratio (width/height):</div>

    * <div data-tips="true" data-tips-type="tip">Between [1/16, 16] (for seedream\-5\-0\-pro, 5\-0\-lite, 4\-5 and 4\-0)</div>
    * <div data-tips="true" data-tips-type="tip">Between [1/3, 3] (for seedream\-3\-0\-t2i)</div>
  * <div data-tips="true" data-tips-type="tip">Width and height (px): \> 14</div>
  * <div data-tips="true" data-tips-type="tip">Size: Up to 30 MB</div>
  * <div data-tips="true" data-tips-type="tip">Total pixels: No more than <code>6000x6000=36000000</code> (The total pixel limit applies to the <strong>product of the single image’s width and height</strong> , rather than to either dimension individually.)</div>
* <div data-tips="true" data-tips-type="tip">Reference images: seedream\-5\-0\-pro supports up to 10 reference images. seedream\-5\-0\-lite, 4\-5 and 4\-0 support up to 14 reference images.</div>

---

**size** `String`

<Tabs>
<Tab zoneid="w8zpDcbhG4" title="Seedream-5-0-pro">
<TabTitle>Seedream-5-0-pro</TabTitle>

Specify the output image dimensions. Two methods are available, but they cannot be used at the same time.

* Method 1: Specify the width and height of the generated image in pixels (`widthxheight`):

  * Default value: `1024x1024`
  * Total pixels range: [`1280x720`(921,600), `2048x2048x1.1025`(4,624,220)]
  * Aspect ratio range: [1/16, 16]

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>

<div data-tips="true" data-tips-type="warning">When using method 1, the total pixel range, aspect ratio range, and multiple\-of\-16 requirement must all be satisfied. The total pixel limit applies to the <strong>product of the single image’s width and height</strong>, rather than to either dimension individually.</div>

* <div data-tips="true" data-tips-type="warning"><strong>Valid example</strong>: <code>2048x1024</code></div>

  <div data-tips="true" data-tips-type="warning">Total pixel count: 2048x1024=2,097,152, which is within the acceptable range of [921,600, 4,624,220]. Aspect ratio: 2048/1024=2, which is within the acceptable range of [1/16, 16].   </div>
* <div data-tips="true" data-tips-type="warning"><strong>Invalid example</strong>: <code>512x512</code></div>

  <div data-tips="true" data-tips-type="warning">Total pixel count: 512x512=262,144, which does not meet the minimum requirement.   </div>
* Method 2: Specify the resolution level of the generated image, and describe its aspect ratio, shape, or purpose in the prompt using natural language. The model determines the final image size.

  * Optional values: `1K`, `2K`

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>

<div data-tips="true" data-tips-type="warning">When using method 2 and describing a specific aspect ratio in the prompt, refer to the table below for width and height pixel values of the generated image:</div>

<div data-tips="true" data-tips-type="warning">
|Resolution |Aspect ratio |Width and Height Pixel Values |
|---|---|---|
|1K |1:1 |1024x1024 |
||4:3 |1152x864 |
||3:4 |864x1152 |
||16:9 |1424x800 |
||9:16 |800x1424 |
||3:2 |1248x832 |
||2:3 |832x1248 |
||21:9 |1568x672 |
|2K |1:1 |2048x2048 |
||4:3 |2368x1776 |
||3:4 |1776x2368 |
||16:9 |2816x1584 |
||9:16 |1584x2816 |
||3:2 |2496x1664 |
||2:3 |1664x2496 |
||21:9 |3136x1344 |
</div>

</Tab>
<Tab zoneid="H4GFCS7POW" title="Seedream-5-0-lite">
<TabTitle>Seedream-5-0-lite</TabTitle>

Specify the output image dimensions. Two methods are available, but they cannot be used at the same time.

* Method 1 | Specify the width and height of the generated image in pixels:

  * Default value: `2048x2048`
  * Total pixels range: [`2560x1440`(3,686,400), `4096x4096`(16,777,216)]
  * Aspect ratio range: [1/16, 16]

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Note</div>

<div data-tips="true" data-tips-type="tip">When using method 1, both the total pixel range and the aspect ratio range must be satisfied simultaneously. The total pixel limit applies to the <strong>product of the single image’s width and height</strong>, rather than to either dimension individually.</div>

* <div data-tips="true" data-tips-type="tip"><strong>Valid example</strong>: <code>3750x1250</code></div>

  <div data-tips="true" data-tips-type="tip">Total pixel count: 3750x1250=4,687,500, which is within the acceptable range of [3686400, 16777216]. Aspect ratio: 3750/1250=3, which is within the acceptable range of [1/16, 16].   </div>
* <div data-tips="true" data-tips-type="tip"><strong>Invalid example</strong>: <code>1500x1500</code></div>

  <div data-tips="true" data-tips-type="tip">Total pixel count: 1500x1500 = 2,250,000, which does not meet the minimum requirement of 3,686,400. Aspect ratio: 1500/1500 = 1, which meets the range of [1/16, 16]. But it's invalid as it only meets one of the two requirements.   </div>
* Method 2 | Specify the resolution of the generated image, and describe its aspect ratio, shape, or purpose in the prompt using natural language. You let the model determine the width and height.

  * Optional values: `2K`, `3K`, `4K`

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>

<div data-tips="true" data-tips-type="warning">When using method 2 and describing a specific aspect ratio in the prompt, refer to the table below for width and height pixel values of the generated image:</div>

<div data-tips="true" data-tips-type="warning">
|Resolution |Aspect ratio |Width and Height Pixel Values |
|---|---|---|
|2K |1:1 |2048x2048 |
||4:3 |2304x1728 |
||3:4 |1728x2304 |
||16:9 |2848x1600 |
||9:16 |1600x2848 |
||3:2 |2496x1664 |
||2:3 |1664x2496 |
||21:9 |3136x1344 |
|3K |1:1 |3072x3072 |
||4:3 |3456x2592 |
||3:4 |2592x3456 |
||16:9 |4096x2304 |
||9:16 |2304x4096 |
||2:3 |2496x3744 |
||3:2 |3744x2496 |
||21:9 |4704x2016 |
|4K |1:1 |4096x4096 |
||3:4 |3520x4704 |
||4:3 |4704x3520 |
||16:9 |5504x3040 |
||9:16 |3040x5504 |
||2:3 |3328x4992 |
||3:2 |4992x3328 |
||21:9 |6240x2656 |
</div>

</Tab>
<Tab zoneid="Z89Mbf8pkL" title="Seedream-4-5">
<TabTitle>Seedream-4-5</TabTitle>

Specify the output image dimensions. Two methods are available, but they cannot be used at the same time.

* Method 1 | Specify the width and height of the generated image in pixels:

  * Default value: `2048x2048`
  * Total pixels range: [`2560x1440=3,686,400`, `4096x4096=16,777,216`]
  * Aspect ratio range: [1/16, 16]

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>

<div data-tips="true" data-tips-type="warning">When using Method 1, both the total pixel range and the aspect ratio range must be satisfied simultaneously. The total pixel limit applies to the <strong>product of the single image’s width and height</strong>, rather than to either dimension individually.</div>

* <div data-tips="true" data-tips-type="warning"><strong>Valid example</strong>: <code>3750x1250</code></div>

  <div data-tips="true" data-tips-type="warning">Total pixel count: 3750x1250=4,687,500, which is within the acceptable range of [3,686,400, 16,777,216]. Aspect ratio: 3750/1250=3, which is within the acceptable range of [1/16, 16].   </div>
* <div data-tips="true" data-tips-type="warning"><strong>Invalid example</strong>: <code>1500x1500</code></div>

  <div data-tips="true" data-tips-type="warning">Total pixel count: 1500x1500 = 2,250,000, which does not meet the minimum requirement of 3,686,400. Aspect ratio: 1500/1500 = 1, which meets the range of [1/16, 16]. But it's invalid as it only meets one of the two requirements.   </div>
* Method 2 | Specify the resolution of the generated image, and describe its aspect ratio, shape, or purpose in the prompt using natural language. You let the model determine the width and height.

  * Optional values: `2K`, `4K`

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>

<div data-tips="true" data-tips-type="warning">When using method 2 and describing a specific aspect ratio in the prompt, refer to the table below for width and height pixel values of the generated image:</div>

<div data-tips="true" data-tips-type="warning">
|Resolution |Aspect ratio |Width and Height Pixel Values |
|---|---|---|
|2K |1:1 |2048x2048 |
||4:3 |2304x1728 |
||3:4 |1728x2304 |
||16:9 |2848x1600 |
||9:16 |1600x2848 |
||3:2 |2496x1664 |
||2:3 |1664x2496 |
||21:9 |3136x1344 |
|4K |1:1 |4096x4096 |
||3:4 |3520x4704 |
||4:3 |4704x3520 |
||16:9 |5504x3040 |
||9:16 |3040x5504 |
||2:3 |3328x4992 |
||3:2 |4992x3328 |
||21:9 |6240x2656 |
</div>

</Tab>
<Tab zoneid="KSU1A90Kst" title="Seedream-4-0">
<TabTitle>Seedream-4-0</TabTitle>

Specify the output image dimensions. Two methods are available, but they cannot be used at the same time.

* Method 1 | Specify the width and height of the generated image in pixels:

  * Default value: `2048x2048`
  * Total pixels range: [`1280x720=921,600`, `4096x4096=16,777,216`]
  * Aspect ratio range: [1/16, 16]

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>

<div data-tips="true" data-tips-type="warning">When using method 1, both the total pixel range and the aspect ratio range must be satisfied simultaneously. The total pixel limit applies to the <strong>product of the single image’s width and height</strong>, rather than to either dimension individually.</div>

* <div data-tips="true" data-tips-type="warning"><strong>Valid example</strong>: <code>1600x600</code></div>

  <div data-tips="true" data-tips-type="warning">Total pixel count: 1600x600 = 960,000, which is within the acceptable range of [921,600, 16,777,216]. Aspect ratio: 1600/600 = 8/3, which is within the acceptable range of [1/16, 16].   </div>
* <div data-tips="true" data-tips-type="warning"><strong>Invalid example</strong>: <code>800x800</code></div>

  <div data-tips="true" data-tips-type="warning">Total pixel count: 800x800 = 640,000, which does not meet the minimum requirement of 921,600. Aspect ratio: 800/800 = 1, which meets the range of [1/16, 16]. But it's invalid as it only meets one of the two requirements.   </div>
* Method 2 | Specify the resolution of the generated image, and describe its aspect ratio, shape, or purpose in the prompt using natural language. You let the model determine the width and height.

  * Optional values: `1K`, `2K`, `4K`

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>

<div data-tips="true" data-tips-type="warning">When using method 2 and describing a specific aspect ratio in the prompt, the model maps it to the following actual width and height pixel values:</div>

<div data-tips="true" data-tips-type="warning">
|Resolution |Aspect ratio |Width and Height Pixel Values |
|---|---|---|
|1K |1:1 |1024x1024 |
||4:3 |1152x864 |
||3:4 |864x1152 |
||16:9 |1280x720 |
||9:16 |720x1280 |
||3:2 |1248x832 |
||2:3 |832x1248 |
||21:9 |1512x648 |
|2K |1:1 |2048x2048 |
||4:3 |2304x1728 |
||3:4 |1728x2304 |
||16:9 |2848x1600 |
||9:16 |1600x2848 |
||3:2 |2496x1664 |
||2:3 |1664x2496 |
||21:9 |3136x1344 |
|4K |1:1 |4096x4096 |
||3:4 |3520x4704 |
||4:3 |4704x3520 |
||16:9 |5504x3040 |
||9:16 |3040x5504 |
||2:3 |3328x4992 |
||3:2 |4992x3328 |
||21:9 |6240x2656 |
</div>

</Tab>
<Tab zoneid="VmxeB3c3mw" title="seedream-3-0-t2i">
<TabTitle>seedream-3-0-t2i</TabTitle>

Set the width and height of the generated image in pixels.

* Default value: `1024x1024`
* The value range of total pixels: [`512x512`(262,144), `2048x2048`(4,194,304)]

  Recommended width and height:

| Aspect ratio | Width and height in pixels Value |
| ------------ | -------------------------------- |
| 1:1          | `1024x1024`                    |
| 4:3          | `1152x864`                     |
| 3:4          | `864x1152`                     |
| 16:9         | `1280x720`                     |
| 9:16         | `720x1280`                     |
| 3:2          | `1248x832`                     |
| 2:3          | `832x1248`                     |
| 21:9         | `1512x648`                     |

</Tab>
</Tabs>

---

**seed** `integer` `Default: -1`

> Only seedream\-3\-0\-t2i supports this parameter.

A random seed that controls the randomness of the generated content. The value range is [\-1, 2147483647].

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>

* <div data-tips="true" data-tips-type="warning">For the same request, the model will produce different results when using different seed values. For example, leaving the seed unspecified, setting it to \-1 (meaning use a random number), or manually changing the seed will all lead to different outputs.</div>
* <div data-tips="true" data-tips-type="warning">When the same seed is used for the same request, the model will generate similar results, but exact duplication is not guaranteed.</div>

---

**sequential_image_generation** `string` `Default: disabled`

> This parameter is only supported on seedream\-5\-0\-lite, 4\-5 and 4\-0. seedream\-5\-0\-pro does not support this parameter. Passing it will cause an error. See [batch image output](https://docs.byteplus.com/en/docs/ModelArk/1824121#b4da5e23) for an example.

Whether to disable the batch generation feature.

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>

<div data-tips="true" data-tips-type="tip">Description</div>

<div data-tips="true" data-tips-type="tip">Batch image generation: a batch of thematically related images generated based on your input content.</div>

Valid values:

* `auto`: The model automatically determines whether to return multiple images and the number of returned images based on the user's prompt.
* `disabled`: Only one image is generated.

---

**sequential_image_generation_options** `object`

> Only seedream\-5\-0\-lite, 4\-5 and 4\-0 support this parameter. seedream\-5\-0\-pro does not support this parameter. Passing it will cause an error.

Configuration for the batch image generation feature; Only effective when **sequential_image_generation** is set to `auto`.

Attributes

---

sequential_image_generation_options. **max_images** `integer` `Default: 15`

Specifies the maximum number of images to generate in this request.

* Value range: [1, 15]

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>

<div data-tips="true" data-tips-type="tip">Description</div>

<div data-tips="true" data-tips-type="tip">The actual number of generated images is determined jointly by <strong>max_images</strong> and the number of input reference images. <strong>Number of input reference images + Number of generated images ≤ 15</strong> .</div>

---

**stream** `boolean` `Default: false`

> Only seedream\-5\-0\-lite, 4\-5 and 4\-0 support this parameter. seedream\-5\-0\-pro does not support this parameter. Passing it will cause an error. See [Streaming Output](https://docs.byteplus.com/en/docs/ModelArk/1824121#914db3a9) for an example.

Whether to enable streaming output mode.

* `false`: All output images are returned at once.
* `true`: Each output image is returned immediately after generated. Applicable for both single and batch image generation.

---

**guidance_scale** `float`

> Default value for seedream\-3\-0\-t2i: 2.5

> seedream\-5\-0\-pro, 5\-0\-lite, 4\-5 and 4\-0 are not supported.

This parameter controls how closely the generated image follows the prompt, affecting the model's degree of creative freedom. A higher value reduces freedom and increases adherence to the prompt.

Valid values: [`1`, `10`]

---

**output_format** **<mark></mark><sup>new</mark>** `string` `Default: jpeg`

> Only seedream\-5\-0\-pro and seedream\-5\-0\-lite support this parameter.

Specifies the format of the output image.

* `png`
* `jpeg`

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>

<div data-tips="true" data-tips-type="tip">For the seedream\-4\-5/4\-0 and seedream\-3\-0\-t2i models, the default file format for generated images is jpeg, and custom settings are not supported.</div>

---

**response_format** `string` `Default: url`

Specifies how the generated images are returned.

The generated image can be returned in the following two ways:

* `url`: Returns a download link for the image. **The link is valid for 24 hours after the image is generated.**
* `b64_json`: Returns the image data in JSON as a Base64\-encoded string.

---

**watermark** `boolean` `Default: true`

Adds a watermark to the generated image.

* `false`: No watermark.
* `true`: Adds a "AI generated" watermark on the bottom\-right corner of the image.

---

**optimize_prompt_options** `object`

> Only seedream\-5\-0\-pro, seedream\-5\-0\-lite, seedream\-4\-5 and seedream\-4\-0 support this parameter.

Configuration for prompt optimization feature.

optimize_prompt_options. **mode** `string` `Default: standard`

Set the mode for the prompt optimization feature.

* `standard`: Higher quality, longer generation time.
* `fast`: Faster but at a more average quality. seedream\-5\-0\-pro, seedream\-5\-0\-lite and seedream\-4\-5 do not support this mode.

---

<span id="7P96iLnc"></span>

## Response parameters

<span id="Hrya4y9k"></span>

### Streaming response parameters

See [Streaming Response](https://docs.byteplus.com/en/docs/ModelArk/1824137).

<span id="1AxnwQZN"></span>

### Non\-streaming response parameters

---

**model** `String`

The model ID used for image generation (`model name-version`).

---

**created** `integer`

The Unix timestamp in seconds of the creation time of the request.

---

**data** `array`

Information of the output images.

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>

<div data-tips="true" data-tips-type="tip">Description</div>

<div data-tips="true" data-tips-type="tip">When generating a batch of images with the seedream\-5\-0\-lite, 4\-5 and 4\-0 models, if an image fails to generate:</div>

* <div data-tips="true" data-tips-type="tip">If the failure is due to the rejection by content filter: The next generation task will still be requested, other image generation tasks in the same request will not be affected.</div>
* <div data-tips="true" data-tips-type="tip">If the failure is due to an internal service error (500): The next picture generation task will not be requested.</div>

Possible type

Image information `object`

Information of the generated image.

Attributes

data. **url** `string`

The URL of the image, returned when **response_format** is specified as `url`. This link will expire **within 24 hours** of generation. Be sure to save the image before expiration.

---

data. **b64_json** `string`

The Base64 information of the image; returned when **response_format** is specified as `b64_json`.

---

data. **output_format** `string`

> Only seedream\-5\-0\-pro supports this field.

The format of the output image.

---

data. **size** `string`

> Only seedream\-5\-0\-pro, seedream\-5\-0\-lite, 4\-5 and 4\-0 support this field.

The width and height of the image in pixels, in the format `<width>x<height>`, such as `2048×2048`.

---

Error message `object`

Error message for a failed image generation.

Attributes

data. **error** `Object`

Error message structure.

Attributes

---

data.error. **code**

The error code for a failed image generation. See [Error Codes](https://docs.byteplus.com/en/docs/ModelArk/1299023).

---

data.error. **message**

Error message for a failed image generation.

---

**usage** `Object`

Usage information for the current request.

Attributes

---

usage. **generated_images** `integer`

The number of images successfully generated by the model, excluding failed generations.

**Note** : Billing is based on the number of successfully generated images.

---

usage. **input_images** **<mark></mark><sup>new</mark>** `integer`

> Only seedream\-5\-0\-pro returns this field.

The number of images input to the model.

---

usage. **output_tokens** `integer`

The number of tokens consumed for the images generated by the model.

The calculation logic is to calculate `sum(image width*image height)/256` and then round the result to an integer.

---

usage. **total_tokens** `integer`

The total number of tokens consumed by this request.

This value is the same as **output_tokens** as input tokens are currently not calculated.

&nbsp;

**error** `object`

The error message for this request, if any.

Attributes

---

error. **code** `String`

See [Error Codes](https://docs.byteplus.com/en/docs/ModelArk/1299023).

---

error. **message** `String`

Error message
