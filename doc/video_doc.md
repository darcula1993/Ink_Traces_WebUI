`POST https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks` [Try](https://api.byteplus.com/api-explorer/?action=CreateContentsGenerationsTasks&groupName=Video%20Generation%20API&serviceCode=ark&version=2024-01-01)

This topic describes the input and output parameters of the API for creating video generation tasks. The model generates a video based on the input text, images, audio, videos, or sample task ID. After generation is complete, you can query the task and obtain the generated video.

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">New model available</div>


<div data-tips="true" data-tips-type="warning">Dreamina Seedance 2.5 is now fully available to the public. You can call the API and try the model online on the BytePlus ModelArk platform. Before calling the model, <strong>please carefully read </strong><a href="https://docs.byteplus.com/en/docs/ModelArk/2607688#2.5_compatibility"><strong>Must\-read before use</strong></a><strong> to ensure that you correctly set the task type and configure parameters</strong> .</div>


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Model activation</div>


<div data-tips="true" data-tips-type="tip">Before activating Dreamina Seedance 2.5 or Dreamina Seedance 2.0 series models, make sure that you have purchased a corresponding <a href="https://console.byteplus.com/common-buy/ModelArk%7C%7Cd7d6aanpgiftptb9ajcg">resource pack</a> with available quota.</div>


<div data-tips="true" data-tips-type="tip">For detailed rules, see <a href="https://docs.byteplus.com/en/docs/ModelArk/2191775">Resource packs for Dreamina Seedance 2.0 series models</a>.</div>


<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Limited\-time discount</div>


<div data-tips="true" data-tips-type="warning">Dreamina Seedance 2.0 mini and Dreamina Seedance 2.0 fast are available at limited\-time discounted rates from 14:00 (UTC+8) on August 7 through 14:00 (UTC+8) on September 7:</div>



* <div data-tips="true" data-tips-type="warning"><strong>Seedance 2.0 mini</strong> : 40% of the list price, starting at approximately USD 0.032 per second for 720p output.</div>


* <div data-tips="true" data-tips-type="warning"><strong>Seedance 2.0 fast</strong> : 75% of the list price, starting at approximately USD 0.09 per second for 720p output.</div>




**Model capabilities**


* **Dreamina Seedance 2.5<mark><sup>new</sup></mark>** (video with audio / silent video)

   * **Multimodal reference\-to\-video** : Input reference images (0–30), reference videos (0–10), reference audio clips (0–10), and an optional text prompt to generate one target video. Audio\-only input is supported. The model supports generating new videos, editing videos, extending videos, and coherently generating videos up to 30 seconds long.

   * **Image\-to\-video (first and last frames)**  : Input a first\-frame image, a last\-frame image, and an optional text prompt to generate one target video.

   * **Image\-to\-video (first frame)**  : Input a first\-frame image and an optional text prompt to generate one target video.

   * **Text\-to\-video** : Input a text prompt to generate one target video.

* **Dreamina Seedance 2.0 series** (video with audio / silent video)

   * **Multimodal reference\-to\-video** : Input reference images (0–9), reference videos (0–3), reference audio clips (0–3), and an optional text prompt to generate one target video. Audio\-only input is not supported; include at least one reference image or video. The models support generating new videos, editing videos, and extending videos.

   * **Image\-to\-video (first and last frames)**  : Input a first\-frame image, a last\-frame image, and an optional text prompt to generate one target video.

   * **Image\-to\-video (first frame)**  : Input a first\-frame image and an optional text prompt to generate one target video.

   * **Text\-to\-video** : Input a text prompt to generate one target video.

* **Dreamina Seedance 1.5 pro** (video with audio / silent video)

   * Supports image\-to\-video (first and last frames), image\-to\-video (first frame), and text\-to\-video.

* **Dreamina Seedance 1.0 pro**

   * Supports image\-to\-video (first and last frames), image\-to\-video (first frame), and text\-to\-video.

* **Dreamina Seedance 1.0 pro fast**

   * Supports image\-to\-video (first frame) and text\-to\-video.



**Parameter input methods**

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">tip</div>



* <div data-tips="true" data-tips-type="tip">For <code>resolution</code>, <code>ratio</code>, <code>duration</code>, <code>frames</code>, <code>seed</code>, <code>camera_fixed</code>, and <code>watermark</code>, all models support both passing parameters directly in the request body and appending <code>--[parameters]</code> after the text prompt.</div>


* <div data-tips="true" data-tips-type="tip">Supported parameters and values vary by model. For details, see <a href="https://docs.byteplus.com/en/docs/ModelArk/2298881#9fe4cce0">Set video output specifications</a>. When a parameter or value is invalid or unsupported:</div>


   * <div data-tips="true" data-tips-type="tip"><strong>Conventional method (recommended)</strong> : Pass parameters directly in the request body. This method uses strict validation and returns an error for invalid parameters.</div>


   * <div data-tips="true" data-tips-type="tip"><strong>Legacy method</strong> : Append <code>--[parameters]</code> after the text prompt. Invalid parameters are ignored or cause an error.</div>



**Conventional method (recommended): Pass parameters directly in the request body**

```json
{
    "model": "seedance-1-5-pro-251215",
    "content": [
        {
            "type": "text",
            "text": "The kitten is yawning at the camera."
        }
    ],
    "resolution": "720p",
    "ratio": "16:9",
    "duration": 5,
    "seed": 11,
    "camera_fixed": false,
    "watermark": true
}
```


**Weak\-validation method: Append **  **`--[parameters]`**  ** after the text prompt**

```json
{
    "model": "seedance-1-5-pro-251215",
    "content": [
        {
            "type": "text",
            "text": "The kitten is yawning at the camera. --rs 720p --rt 16:9 --dur 5 --seed 11 --cf false --wm true"
        }
    ]
}
```



&nbsp;


<Tabs>
<Tab zoneid="hRspgFkFD0" title="Try">
<TabTitle>Try</TabTitle>

[去调试](https://api.byteplus.com/api-explorer/?action=CreateContentsGenerationsTasks&groupName=Video%20Generation%20API&serviceCode=ark&version=2024-01-01)



</Tab>
<Tab zoneid="sw73KhJ3nq" title="Quick start">
<TabTitle>Quick start</TabTitle>

[Playground](https://ai.byteplus.com/ark/region:ap-southeast-1/experience/vision) | [Model list](https://docs.byteplus.com/en/docs/ModelArk/1330310) | [Model billing](https://docs.byteplus.com/en/docs/ModelArk/1544106#8f25f772) | [API key](https://ai.byteplus.com/ark/region:ap-southeast-1/apiKey?apikey=%7B%7D)

[API tutorial](https://docs.byteplus.com/en/docs/ModelArk/1366799) | [API reference](https://docs.byteplus.com/en/docs/ModelArk/Video_Generation_API) | [FAQs](https://docs.byteplus.com/en/docs/ModelArk/1359411) | [Model activation](https://ai.byteplus.com/ark/region:ap-southeast-1/openManagement?LLM=%7B%7D&tab=ComputerVision)


</Tab>
<Tab zoneid="SNWAQnioN8" title="Authentication">
<TabTitle>Authentication</TabTitle>

This API supports only API Key authentication. Obtain a long\-term API Key on the [API keys](https://ai.byteplus.com/ark/region:ap-southeast-1/apiKey?apikey=%7B%7D) page.


</Tab>
</Tabs>


<span id="request-parameters"></span>
## Request parameters

<span id="request-body"></span>
### Request body


**model** `string` `Required`  |  Model ID

ID of the model you need to call. You can [activate a model service](https://ai.byteplus.com/ark/region:ap-southeast-1/openManagement?LLM=%7B%7D&tab=ComputerVision) and [query the model ID](https://docs.byteplus.com/en/docs/ModelArk/1330310).

You can also use an endpoint ID to call a model, querying its rate limits, billing method (prepaid or postpaid), and status, and using its advanced capabilities such as monitoring and security. For more information, refer to [Obtaining an endpoint ID](https://docs.byteplus.com/en/docs/ModelArk/1099522).



**content** `object[]` `Required`  |  Input content list

The references provided to the model for video generation, supporting text, image, audio, video, and sample task ID.

The following combinations are supported:


* Text

* Text (optional) + image

* Text (optional) + video

* Text (optional) + audio (Dreamina Seedance 2.5 supports audio\-only input)

* Text (optional) + image + audio

* Text (optional) + image + video

* Text (optional) + video + audio

* Text (optional) + image + video + audio

* Sample task ID: A sample video successfully generated using a Seedance model. The model can generate a high\-quality final video based on the sample.


<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>


<div data-tips="true" data-tips-type="warning">Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series models do not support directly uploading reference images or videos that contain real human faces. ModelArk provides the following solutions to help you create videos with portrait assets. For details, see <a href="https://docs.byteplus.com/en/docs/ModelArk/2608626">Create portrait videos with Dreamina Seedance models</a>.</div>



* <div data-tips="true" data-tips-type="warning">Supports using original outputs containing human faces from certain models as input assets</div>


* <div data-tips="true" data-tips-type="warning">Supports using preset digital characters as input assets</div>


* <div data-tips="true" data-tips-type="warning">Supports using authorized real\-person assets as input assets</div>




**Text** `object`

The input text information for the model to generate a video.


**type** `string` `Required`  |  Content type

`content.type`

The type of the input content. In this case, set the value to `text`.



**text** `string` `Required`  |  Text prompt

`content.text`

Text prompt input to the model, describing the expected generated video.

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>



* <div data-tips="true" data-tips-type="tip"><strong>Supported prompt languages</strong> : All models support English prompts.</div>


   * <div data-tips="true" data-tips-type="tip"><strong>Dreamina Seedance 2.5</strong> additionally supports Spanish, Indonesian, Portuguese, Japanese, Malay, Thai, Arabic, Vietnamese, and Korean.</div>


   * <div data-tips="true" data-tips-type="tip"><strong>Dreamina Seedance 2.0 series</strong> additionally supports Spanish, Indonesian, Portuguese, and Japanese.</div>


* <div data-tips="true" data-tips-type="tip">Recommended prompt length: no more than 500 Chinese characters or 1,000 English words. Lengthy text will lead to scattered information, and the model may ignore details and only focus on key points, resulting in missing elements in the generated video.</div>


* <div data-tips="true" data-tips-type="tip">See <a href="https://docs.byteplus.com/en/docs/ModelArk/2222480">Dreamina Seedance 2.0 series prompt guide</a> for more tips on using prompts.</div>





**Image** `object`

The input image information for the model to generate a video.


**type** `string` `Required`  |  Content type

`content.type`

The type of the input content. In this case, set the value to `image_url`. Supports image URL or image Base64 encoding.



**image_url** `object` `Required`  |  Image object

`content.image_url`

The input image object for the model.


**url** `string` `Required`  |  Image source

`content.image_url.url`

Accepts image URL, Base64\-encoded image, or asset ID.


* URL: Enter the publicly accessible URL of the image.

* Base64 encoding: Convert the local file to a Base64\-encoded string, then submit to the model. Follow the format: `data:image/<image format>;base64,<Base64 encoding>`. Note that `<image format>` must be lowercase, for example `data:image/png;base64,{base64_image}`.

* Asset ID: The URI of the digital character used for video generation. It follows the format `asset://<ASSET_ID>` and can be obtained from the [Digital characters library](https://ai.byteplus.com/ark/region:ap-southeast-1/experience/gen_video?model=dreamina-seedance-2-0-260128).


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Requirements for uploading a single image</div>



* <div data-tips="true" data-tips-type="tip">Format: <code>jpeg</code>, <code>png</code>, <code>webp</code>, <code>bmp</code>, <code>tiff</code>, or <code>gif</code>. Dreamina Seedance 1.5 pro and later models also support <code>heic</code> and <code>heif</code>.</div>


* <div data-tips="true" data-tips-type="tip">Aspect ratio (width/height): <code>[0.4, 2.5]</code></div>


* <div data-tips="true" data-tips-type="tip">Width and height (px): <code>[300, 6000]</code></div>


* <div data-tips="true" data-tips-type="tip">Size:</div>


   * <div data-tips="true" data-tips-type="tip">Single image must be less than 30 MB</div>


   * <div data-tips="true" data-tips-type="tip">Request body size does not exceed 64 MB.</div>


   * <div data-tips="true" data-tips-type="tip">Do not use Base64 encoding for large files.</div>


* <div data-tips="true" data-tips-type="tip">Number of images:</div>


   * <div data-tips="true" data-tips-type="tip">Image\-to\-video (first frame): 1</div>


   * <div data-tips="true" data-tips-type="tip">Image\-to\-video (first and last frames): 2</div>


   * <div data-tips="true" data-tips-type="tip">Dreamina Seedance 2.5 multimodal reference\-to\-video: 1–30 images</div>


   * <div data-tips="true" data-tips-type="tip">Seedance 2.0 series multimodal\-reference to video: 1–9 images</div>





**role** `string` `Required under certain conditions`  |  Role/purpose

`content.role`

The location or purpose of the image.


Image\-to\-video (first frame)


* **Supported models:**  All models

* **Values** : You need to pass in one **image_url** object, with the role field set to `first_frame` or leave **role** blank.



Image\-to\-video (first and last frames)


* **Supported models:**  Dreamina Seedance 2.5, Dreamina Seedance 2.0 series, Dreamina Seedance 1.5 pro, and Dreamina Seedance 1.0 pro.

* **Values** : Two **image_url** objects must be provided, and the role field is required.

   * Role of the first frame: `first_frame`

   * Role of the last frame: `last_frame`


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>


<div data-tips="true" data-tips-type="tip">The first\-frame and last\-frame images can be identical.</div>


<div data-tips="true" data-tips-type="tip">If the aspect ratios of the first and last frame images are inconsistent, the first frame image takes precedence, and the last frame image will be automatically cropped to fit.</div>




Image\-to\-video (reference images)


* **Supported models:**  Dreamina Seedance 2.5 (1–30 images) and Dreamina Seedance 2.0 series (1–9 images)

* **Values** : Required. The **role** field for each reference image must be set to `reference_image`


&nbsp;

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>



* <div data-tips="true" data-tips-type="warning"><strong>Image\-to\-video (first frame)</strong> , <strong>image\-to\-video (first and last frames)</strong> , and <strong>multimodal reference\-to\-video</strong> (including reference images, videos, and audio) are mutually exclusive scenarios and <strong>cannot be mixed</strong> .</div>


* <div data-tips="true" data-tips-type="warning">For multimodal reference\-based video generation, you can specify reference images as the first and/or last frame in the prompt to indirectly achieve a "first/last frame + multimodal references" effect. If you need to strictly ensure the first and last frames exactly match the specified images, use <strong>image to video \- first and last frames</strong> instead (set <code>role</code> to <code>first_frame</code> or <code>last_frame</code>).</div>





**Video** `object`

Reference video provided to the model. Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series models support video input.

ModelArk trusts face\-containing videos generated by these models. You can use the **original face\-containing videos generated by these models under your account within the past 30 days** as input assets. For details, see [Trust model outputs as input assets](https://docs.byteplus.com/en/docs/ModelArk/2608626#trust-model-output).


**type** `string` `Required`  |  Content type

`content.type`

Type of the input; in this case, set to `video_url`.



**video_url** `object` `Required`  |  Video object

`content.video_url`

The video object provided to the model.


**url** `string` `Required`  |  Video source

`content.video_url.url`

Video URL or asset ID.


* Video URL: Enter the public URL of the video.

* Asset ID: The URI of the digital character used for video generation. It follows the format `asset://<ASSET_ID>` and can be obtained from the [digital characters library](https://ai.byteplus.com/ark/region:ap-southeast-1/experience/gen_video?model=dreamina-seedance-2-0-260128).


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Video input requirements</div>



* <div data-tips="true" data-tips-type="tip">Video format: <code>mp4</code>, <code>mov</code>. Supported encoding formats are listed in the table below.</div>


* <div data-tips="true" data-tips-type="tip">Resolution: <code>480p</code>, <code>720p</code>, <code>1080p</code>, <code>4k</code></div>


* <div data-tips="true" data-tips-type="tip">Duration:</div>


   * <div data-tips="true" data-tips-type="tip"><strong>Dreamina Seedance 2.5:</strong> Each video must be 2–30 seconds long. You can submit up to 10 reference videos with a total duration of no more than 30 seconds.</div>


   * <div data-tips="true" data-tips-type="tip"><strong>Dreamina Seedance 2.0 series:</strong> Each video must be 2–15 seconds long. You can submit up to 3 reference videos with a total duration of no more than 15 seconds.</div>


* <div data-tips="true" data-tips-type="tip">Dimensions:</div>


   * <div data-tips="true" data-tips-type="tip">Aspect ratio (width/height): <code>[0.4, 2.5]</code></div>


   * <div data-tips="true" data-tips-type="tip">Width and height (px): <code>[300, 6000]</code></div>


   * <div data-tips="true" data-tips-type="tip">Total pixels: <code>[640×640=409600, 3326×2494=8295044]</code>, that is, the product of width and height must fall in the range <code>[409600, 8295044]</code>.</div>


* <div data-tips="true" data-tips-type="tip">Size: Each video must not exceed 200 MB.</div>


* <div data-tips="true" data-tips-type="tip">Frame rate (FPS): <code>[24, 60]</code></div>




|Container Format |Common Extension Name |**MIME** |Supported Encodings |
|---|---|---|---|
|MP4 |.mp4 |video/mp4 |Video: H.264/AVC, H.265/HEVC<br><br>Audio: AAC, MP3 |
|QuickTime |.mov |video/quicktime |Video: H.264/AVC, H.265/HEVC<br><br>Audio: AAC, MP3 |





**role** `string` `conditionally required`  |  Role/purpose

`content.role`

Position or purpose of the video. Fixed to `reference_video`.

**Supported models:**  Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series.




**Audio** `object`

Audio provided to the model. Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series models support audio input.


**type** `string` `Required`  |  Content type

`content.type`

Type of the input; in this case, set to `audio_url`. Supports audio URL or Base64\-encoded audio string.



**audio_url** `object` `Required`  |  Audio object

`content.audio_url`

Audio object provided to the model.


**url** `string` `Required`  |  Audio source

`content.audio_url.url`

URL, Base64\-encoded string or asset ID of the audio.


* Audio URL: The publicly accessible URL of the audio.

* Base64 encoding: Convert the local file to a Base64\-encoded string, then submit it to the model. Follow the format: `data:audio/<audio format>;base64,<Base64 encoding>`.

   `<audio format>` must be lowercase, for example, `data:audio/wav;base64,{base64_audio}`.

* Asset ID: The URI of the digital character used for video generation. It follows the format `asset://<ASSET_ID>` and can be obtained from the [digital character library](https://ai.byteplus.com/ark/region:ap-southeast-1/experience/gen_video?model=dreamina-seedance-2-0-260128).


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Audio input requirements</div>



* <div data-tips="true" data-tips-type="tip">Format: <code>wav</code>, <code>mp3</code></div>


* <div data-tips="true" data-tips-type="tip">Duration:</div>


   * <div data-tips="true" data-tips-type="tip"><strong>Dreamina Seedance 2.5:</strong> Each audio clip must be 2–30 seconds long. You can submit up to 10 reference audio clips with a total duration of no more than 30 seconds.</div>


   * <div data-tips="true" data-tips-type="tip"><strong>Dreamina Seedance 2.0 series:</strong> Each audio clip must be 2–15 seconds long. You can submit up to 3 reference audio clips with a total duration of no more than 15 seconds.</div>


* <div data-tips="true" data-tips-type="tip">Size:</div>


   * <div data-tips="true" data-tips-type="tip">Each audio file must not exceed 15 MB.</div>


   * <div data-tips="true" data-tips-type="tip">The request body size must not exceed 64 MB.</div>


   * <div data-tips="true" data-tips-type="tip">Do not use Base64 encoding for large files.</div>





**role** `string` `conditionally required`  |  Role/purpose

`content.role`

Position or purpose of the audio. Fixed to `reference_audio`.

**Supported models:** 


* **Dreamina Seedance 2.5:**  Supports audio\-only input and combining audio with images or videos.

* **Dreamina Seedance 2.0 series:**  Audio\-only input is not supported; include at least one reference image or video.




**Sample** `object`

Generate a final video based on the sample task ID. This feature is supported only by **Dreamina Seedance 1.5 pro** . To learn more about how to use the draft feature and review important notes, see [Draft mode](https://docs.byteplus.com/en/docs/ModelArk/2298881#5acd28c8).


**type** `string` `Required`  |  Content type

`content.type`

Type of input content. In this case, set it to `draft_task`.



**draft_task** `object` `Required`  |  Draft task object

`content.draft_task`

Draft task input to the model.


**id** `string` `Required`  |  Draft task ID

`content.draft_task.id`

Draft task ID. ModelArk will automatically reuse the user inputs used for the draft video ( **model** , content. **text** , content. **image_url** , **generate_audio** , **seed** , **ratio** , **duration** , and **camera_fixed** ) to generate the final video. Other parameters can be specified manually. If not specified, the default values of this model will be used.

Two steps are required:


1. Call this API to generate a draft video.

2. If you confirm that the draft video meets expectations, you can call this API to generate the final video based on the draft video task ID returned in Step 1.


See [Draft mode](https://docs.byteplus.com/en/docs/ModelArk/2298881#5acd28c8) for detailed instructions.



&nbsp;

**Supported models:** 


* `Dreamina Seedance 1.5 pro`




**callback_url** `string`  |  Callback URL

Fill in the callback notification address for the result of this generation task. When the status of the video generation task changes, ModelArk will send a POST request to this address.

The callback request content structure is consistent with the response body of the [Retrieve a video generation task API](https://docs.byteplus.com/en/docs/ModelArk/1521309).

The status returned by the callback can be one of the following values:


* `queued`: In queue.

* `running`: Task is running.

* `succeeded`: Task succeeded. If sending fails, that is, no successful delivery confirmation is received within 5 seconds, the callback is retried three times.

* `failed`: Task failed. If sending fails, that is, no successful delivery confirmation is received within 5 seconds, the callback is retried three times.

* `expired`: Task timed out, that is, the task has been in the `running` or `queued` state for longer than the expiration time. You can set the expiration time via `execution_expires_after`.



**return_last_frame** `boolean` `Default value: false`  |  Return last frame


* `true`: Return the last frame image of the generated video in PNG format. After setting it to `true`, you can get the last frame image via the [Retrieve a video generation task API](https://docs.byteplus.com/en/docs/ModelArk/1521309). Its pixel dimensions are consistent with the generated video, and it has no watermark.

* `false`: Do not return the last frame image of the generated video.


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>


<div data-tips="true" data-tips-type="tip">You can use this parameter to generate multiple consecutive videos. Use the last frame of the previously generated video as the first frame of the next video task to quickly generate a sequence of videos. For an example, see <a href="https://docs.byteplus.com/en/docs/ModelArk/2298881#141cf7fa">Generate multiple consecutive videos</a>.</div>




**service_tier** `string` `Default value: default`  |  Service tier

> Modifying the service tier of a submitted task is not supported.


Specify the service tier type for processing this request. Valid values:


* `default`: Online inference mode, with lower RPM and concurrency quotas (see [Model list](https://docs.byteplus.com/en/docs/ModelArk/1330310)), suitable for scenarios with high requirements for inference efficiency.

* `flex`: Offline inference mode, with higher TPD quota (see [Model list](https://docs.byteplus.com/en/docs/ModelArk/1330310)), priced at 50% of online inference, suitable for scenarios with high tolerance for inference latency. Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series models are not currently supported.



**execution_expires_after** `integer` `Default value: 172800`  |  Task expiration threshold

Task timeout threshold. Specifies the expiration time of the task after submission (unit: second), calculated from the **created at** timestamp. The default value is 172800 seconds, which is 48 hours. Value range: `[3600, 259200]`.

No matter which **service_tier** you use, it is recommended to set an appropriate timeout according to your business scenario. After this time, the task will be automatically terminated and marked as `expired` status.



**generate_audio** `boolean` `Default: true`  |  Generate audio

Controls whether the generated video includes sound synchronized with the footage.


* `true`: The video output by the model includes synchronized audio. The model will automatically generate matching human voice, sound effects and background music based on the text prompt and visual content. It is recommended to put dialogue content in double quotes to optimize the audio generation effect. For example: The man stopped the woman and said: "Remember, you can't point at the moon with your finger in the future."

* `false`: The video output by the model is a silent video.


<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>


<div data-tips="true" data-tips-type="warning">All generated videos with audio are mono, regardless of the number of channels of the input audio.</div>


**Supported models:** 


* `Dreamina Seedance 2.5`

* `Dreamina Seedance 2.0 series`

* `Dreamina Seedance 1.5 pro`



**draft** `boolean` `Default: false`  |  Draft mode

> Only supported by Dreamina Seedance 1.5 pro.


Controls whether to enable draft mode. See [Draft mode](https://docs.byteplus.com/en/docs/ModelArk/2298881#5acd28c8) for detailed instructions and notes.


* `true`: Enable draft mode, generate a preview video to quickly verify whether the scene structure, shot scheduling, subject motion match the prompt intent as expected. It consumes fewer tokens than normal videos, so the usage cost is lower.

* `false`: Disable draft mode and generate a video normally.


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>


<div data-tips="true" data-tips-type="tip">After enabling draft mode, the draft video will be generated in 480p resolution (using other resolutions will cause an error). The last frame return function and offline inference function are not supported.</div>




**safety_identifier** `string`  |  End\-user identifier

Unique identifier of end users, used to help the platform detect users in your application who may violate the ModelArk usage policy. This identifier is an English string, which must be fixed and unique for a single user, and the length cannot exceed 64 characters.

It is recommended to pass in a string generated by hashing the username, user ID or email address to avoid leaking user privacy information.



**priority** `integer` `Default 0`  |  Execution priority

> Supported by Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series.


Sets the execution priority of the current request and determines its position in the queue.

Value range: `[0, 9]`.

A larger value indicates a higher priority.

By default, requests are executed in **FIFO** (First In, First Out) order. After you set a higher priority, the request is inserted before all lower\-priority requests under the same **Endpoint** .

**Example** :

Assume an Endpoint currently has three queued tasks (`status=queued`), all with the default priority of 0.

```text
Queue: [Task A: priority=0] → [Task B: priority=0] → [Task C: priority=0]
```


If you submit a new request with `priority=5`, the request is moved directly to the front of the queue:

```text
Queue: [New request: priority=5] → [Task A: priority=0] → [Task B: priority=0] → [Task C: priority=0]
```


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Note</div>



* <div data-tips="true" data-tips-type="tip">Requests with the same priority are still ordered by FIFO.</div>


* <div data-tips="true" data-tips-type="tip">Priority affects only the queue order. It does not interrupt tasks that are already running (status = <code>running</code>).</div>


* <div data-tips="true" data-tips-type="tip">Priority takes effect only within the same Endpoint and does not affect other Endpoints.</div>


* <div data-tips="true" data-tips-type="tip">Offline inference mode (<code>service_tier=flex</code>) does not support priority configuration.</div>




**resolution** `string`  |  Video resolution

Video resolution.

<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Tip</div>



* <div data-tips="true" data-tips-type="tip">Compared with standard 8\-bit video, Seedance 2.0 4K output uses 10\-bit encoding, preserving richer color gradations and smoother tonal transitions. This makes it suitable for professional video production and HDR content.</div>


* <div data-tips="true" data-tips-type="tip">4K videos are encoded in H.265 (HEVC). Some players and browsers may not support direct playback. For details, see <a href="https://docs.byteplus.com/en/docs/ModelArk/2291680#4k_player">4K player compatibility</a>.</div>



**Supported models and values:** 


* **Dreamina Seedance 2.5:**  Default `720p`; supports `480p` and `720p`.

* **Dreamina Seedance 2.0:**  Default `720p`; supports `480p`, `720p`, `1080p`, and `4k`.

* **Dreamina Seedance 2.0 fast:**  Default `720p`; supports `480p` and `720p`.

* **Dreamina Seedance 2.0 mini:**  Default `720p`; supports `480p` and `720p`.

* **Dreamina Seedance 1.5 pro:**  Default `720p`; supports `480p`, `720p`, and `1080p`.

* **Dreamina Seedance 1.0 pro:**  Default `1080p`; supports `480p`, `720p`, and `1080p`.

* **Dreamina Seedance 1.0 pro fast:**  Default `1080p`; supports `480p`, `720p`, and `1080p`.



**ratio** `string`  |  Video aspect ratio

Aspect ratio of the generated video.


* Supported values: `16:9`, `4:3`, `1:1`, `3:4`, `9:16`, `21:9`, and `adaptive`. The `adaptive` value automatically selects an aspect ratio based on the task type and input.


<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>


<div data-tips="true" data-tips-type="warning">For Dreamina Seedance 2.5 video editing, video extension, first\-frame image\-to\-video, and first\-and\-last\-frame image\-to\-video tasks, <code>ratio</code> only supports <code>adaptive</code>. You cannot specify another aspect ratio. For task definitions, see <a href="https://docs.byteplus.com/en/docs/ModelArk/2607688#2.5_task_type_intro">Task\-specific constraints</a>.</div>



Value restrictions and `adaptive` behavior by model


<span aceTableMode="list" aceTableWidth="1,1.5,3,3,2.5,2.5"></span>
|Task type | |Dreamina Seedance 2.5 |Dreamina Seedance 2.0 series |Dreamina Seedance 1.5 pro |Dreamina Seedance 1.0 series |
|---|---|---|---|---|---|
|Text\-to\-video | |Supports specifying an available aspect ratio or allowing the model to select one based on the prompt<br><br>> Supports `adaptive` or a specified aspect ratio |Supports specifying an available aspect ratio or allowing the model to select one based on the prompt<br><br>> Supports `adaptive` or a specified aspect ratio |Supports specifying an available aspect ratio or allowing the model to select one based on the prompt<br><br>> Supports `adaptive` or a specified aspect ratio |Only supports specifying an available aspect ratio<br><br>> Does not support `adaptive` |
|First\-frame or first\-and\-last\-frame image\-to\-video | |**Automatically preserves the aspect ratio of the first\-frame image**<br><br>> Defaults to and only supports `adaptive` |Supports specifying an available aspect ratio or allowing the model to select one based on the first\-frame image<br><br>> Supports `adaptive` or a specified aspect ratio |Supports specifying an available aspect ratio or allowing the model to select one based on the first\-frame image<br><br>> Supports `adaptive` or a specified aspect ratio |Supports specifying an available aspect ratio or allowing the model to select one based on the first\-frame image<br><br>> Supports `adaptive` or a specified aspect ratio |
|Multimodal video generation |Video editing<br><br>Video extension |**Automatically preserves the aspect ratio of the input video; you cannot specify another ratio**<br><br>> Defaults to and only supports `adaptive` |Supports specifying an available aspect ratio or allowing the model to select one based on the input video<br><br>> Supports `adaptive` or a specified aspect ratio |— |— |
||Reference\-to\-video |Supports specifying an available aspect ratio or allowing the model to select one based on the prompt<br><br>> Supports `adaptive` or a specified aspect ratio |Supports specifying an available aspect ratio or allowing the model to select one based on the prompt<br><br>> Supports `adaptive` or a specified aspect ratio |— |— |




Width and height pixel values corresponding to different aspect ratios

For image to video tasks, when the selected video aspect ratio is inconsistent with the aspect ratio of your uploaded image, ModelArk will crop your image, and the cropping will be centered. See [Image cropping rules](https://docs.byteplus.com/en/docs/ModelArk/2298881#f76aafc8) for detailed rules.


<span aceTableMode="list" aceTableWidth="1,1,1,1,1,1"></span>
|Resolution |Aspect ratio |Dreamina Seedance 2.5 |Dreamina Seedance 2.0 series |Dreamina Seedance 1.5 pro |Dreamina Seedance 1.0 series |
|---|---|---|---|---|---|
|480p |`16:9` |854×480 |864×496 |864×496 |864×480 |
||`4:3` |752×560 |752×560 |752×560 |736×544 |
||`1:1` |640×640 |640×640 |640×640 |640×640 |
||`3:4` |560×752 |560×752 |560×752 |544×736 |
||`9:16` |480×854 |496×864 |496×864 |480×864 |
||`21:9` |992×432 |992×432 |992×432 |960×416 |
|720p |`16:9` |1280×720 |1280×720 |1280×720 |1248×704 |
||`4:3` |1112×834 |1112×834 |1112×834 |1120×832 |
||`1:1` |960×960 |960×960 |960×960 |960×960 |
||`3:4` |834×1112 |834×1112 |834×1112 |832×1120 |
||`9:16` |720×1280 |720×1280 |720×1280 |704×1248 |
||`21:9` |1470×630 |1470×630 |1470×630 |1504×640 |
|1080p<br><br>(Seedance 2.5, Seedance 2.0 fast, and Seedance 2.0 mini are not supported) |`16:9` |— |1920×1080 |1920×1080 |1920×1088 |
||`4:3` |— |1664×1248 |1664×1248 |1664×1248 |
||`1:1` |— |1440×1440 |1440×1440 |1440×1440 |
||`3:4` |— |1248×1664 |1248×1664 |1248×1664 |
||`9:16` |— |1080×1920 |1080×1920 |1088×1920 |
||`21:9` |— |2206×946 |2206×946 |2176×928 |
|4k<br><br>(Only Seedance 2.0 is supported) |`16:9` |— |3840×2160 |— |— |
||`4:3` |— |3326×2494 |— |— |
||`1:1` |— |2880×2880 |— |— |
||`3:4` |— |2494×3326 |— |— |
||`9:16` |— |2160×3840 |— |— |
||`21:9` |— |4398×1886 |— |— |



&nbsp;

**Supported models and defaults:** 


* **Dreamina Seedance 2.5:**  Default `adaptive`.

* **Dreamina Seedance 2.0 series:**  Default `adaptive`.

* **Dreamina Seedance 1.5 pro:**  Default `adaptive`.

* **Dreamina Seedance 1.0 pro:**  Defaults to `16:9` for text\-to\-video and `adaptive` for image\-to\-video.

* **Dreamina Seedance 1.0 pro fast:**  Defaults to `16:9` for text\-to\-video and `adaptive` for image\-to\-video.



**duration** `integer`  |  Video duration

Generated video duration in seconds. Specify either `duration` or `frames`; `frames` takes precedence. To generate a whole\-second video, specify `duration`.

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>


<div data-tips="true" data-tips-type="warning">For Dreamina Seedance 2.5 video editing tasks, <code>duration</code> only supports <code>-1</code>; you cannot specify an output duration.</div>


<div data-tips="true" data-tips-type="warning">The input video must be 4–30 seconds long.</div>


<div data-tips="true" data-tips-type="warning">For task definitions, see <a href="https://docs.byteplus.com/en/docs/ModelArk/2607688#2.5_task_type_intro">Task\-specific constraints</a>.</div>



Behavior when `duration` is `-1`


<span aceTableMode="list" aceTableWidth="1,2.5"></span>
|Model |Behavior when `duration` is `-1` |
|---|---|
|Dreamina Seedance 2.0 series and Dreamina Seedance 1.5 pro |The model selects an appropriate whole\-second video length within the valid `duration` range. |
|Dreamina Seedance 2.5 (video editing) |Automatically keeps the output duration approximately the same as the input duration. The output may be about 0.4 seconds shorter than the input; you cannot specify another duration. |
|Dreamina Seedance 2.5 (other task types) |The model selects an appropriate whole\-second video length within the valid `duration` range. |


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">Returned duration</div>


<div data-tips="true" data-tips-type="tip">The <code>duration</code> returned by the Retrieve a video generation task API is an integer approximation and may differ from the actual duration.</div>



* <div data-tips="true" data-tips-type="tip">Calculation: returned <code>duration</code> = actual total frames / 24, rounded down.</div>


* <div data-tips="true" data-tips-type="tip">Example: For a 133\-frame video, the actual duration is 133 / 24 = 5.54 seconds, while the returned <code>duration</code> is 5.</div>



&nbsp;

**Supported models and values:** 


* **Dreamina Seedance 2.5:**  Default `-1`; supports `[4, 30]` or `-1`.

* **Dreamina Seedance 2.0 series:**  Default `5`; supports `[4, 15]` or `-1`.

* **Dreamina Seedance 1.5 pro:**  Default `5`; supports `[4, 12]` or `-1`.

* **Dreamina Seedance 1.0 pro:**  Default `5`; supports `[2, 12]`.

* **Dreamina Seedance 1.0 pro fast:**  Default `5`; supports `[2, 12]`.



**frames** `integer`  |  Video frame count

> You only need to specify either duration or frames, and frames takes precedence over duration. If you want to generate a video with fractional seconds, it is recommended to specify frames.


Frame count of the generated video. By specifying the number of frames, you can flexibly control the length of the generated video and generate videos with fractional seconds.

Due to the value limit of frames, only certain fractional seconds are supported. You need to calculate the closest number of frames according to the formula.


* Calculation formula: Number of frames = duration × frame rate (24).

* Value range: All integer values in the range `[29, 289]` that fit the format `25 + 4n` are supported, where n is a positive integer.


Example: If you need to generate a 2.4\-second video, the number of frames = 2.4 × 24 = 57.6. However, since frames value cannot be 57.6, you can only select the closest value. The closest number of frames calculated according to 25 + 4n is 57, and the actually generated video is 57 / 24 = 2.375 seconds.

**Supported models** :


* `Dreamina Seedance 1.0 pro`

* `Dreamina Seedance 1.0 pro fast`



**output_format<mark><sup>new</sup></mark>** `string` `Default value: mp4`  |  Output format

Output video format.


* `mp4`: A general\-purpose format with broad compatibility and standard color precision. It can be played directly in browsers, on mobile devices, in media players, and on distribution platforms.

* `mov`: A high\-color\-precision format for professional workflows. It better preserves color and brightness consistency and is suitable for color grading, keying, compositing, and other professional post\-production tasks. For video editing and extension, using MOV for both input and output is recommended.


<div data-tips="true" data-tips-type="tip" data-tips-is-title="true">MOV playback compatibility</div>


<div data-tips="true" data-tips-type="tip">MOV output uses H.264 video encoding, YUV 4:4:4 chroma sampling, and PCM audio encoding. Some players may not support this combination.</div>


<div data-tips="true" data-tips-type="tip">
|Player |macOS |Windows |
|---|---|---|
|IINA |✓ |✕ |
|VLC |✓ |✓ |
|mpv |✓ |✓ |
|ffplay |✓ |✓ |
</div>


**Supported models**


* `Dreamina Seedance 2.5`



**seed** `integer` `Default value: -1`  |  Random seed

Seed integer, used to control the randomness of generated content.

Value range: `[-1, 2147483647]`.

<div data-tips="true" data-tips-type="warning" data-tips-is-title="true">Note</div>



* <div data-tips="true" data-tips-type="warning">For the same request, if the model receives different seed values, such as not specifying a seed value, setting the seed to \-1 (which will be replaced by a random number), or manually changing the seed value, different results will be generated.</div>


* <div data-tips="true" data-tips-type="warning">For the same request, if the model receives the same seed value, similar results will be generated, but complete consistency is not guaranteed.</div>



**Supported models:** 


* `Dreamina Seedance 1.5 pro`

* `Dreamina Seedance 1.0 pro`

* `Dreamina Seedance 1.0 pro fast`



**camera_fixed** `boolean` `Default value: false`  |  Fix camera

> Reference\-image scenarios are not supported.


Whether to fix the camera. Valid values:


* `true`: Fix the camera. ModelArk will append the fixed camera instruction to the user's prompt, but the actual result is not guaranteed.

* `false`: Do not fix the camera.


**Supported models:** 


* `Dreamina Seedance 1.5 pro`

* `Dreamina Seedance 1.0 pro`

* `Dreamina Seedance 1.0 pro fast`



**watermark** `boolean` `Default value: false`  |  Video watermark

Whether the generated video contains a watermark. Valid values:


* `true`: An `AI Generated` watermark will be displayed in the lower right corner of the generated video.

* `false`: The generated video does not contain a watermark.


&nbsp;

<span id="response-parameters"></span>
## Response parameters


**id** `string`  |  Task ID

Video generation task ID. Stored for only 7 days (calculated from the **created at** timestamp), and will be automatically cleared after expiration.


* When `"draft": true` is set, it is the draft video task ID.

* When `"draft": false` is set, it is the normal video task ID.

   The video generation task creation is an asynchronous API. After obtaining the ID, you need to query the status of the video generation task through the [Retrieve a video generation task API](https://docs.byteplus.com/en/docs/ModelArk/1521309). After the task is successful, the `video_url` of the generated video will be output.




