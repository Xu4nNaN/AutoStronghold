package com.autostronghold.app

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * One ONNX model for the Python `onnxruntime` stand-in (src/main/python/onnxruntime):
 * float32 in, float32 out, CPU. Tensors cross the bridge as raw native-order bytes.
 */
class OrtBridge(modelPath: String, threads: Int) {
    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    private var shape = LongArray(0)

    init {
        val options = OrtSession.SessionOptions()
        options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
        if (threads > 0) options.setIntraOpNumThreads(threads)
        session = env.createSession(modelPath, options)
    }

    fun inputNames(): Array<String> = session.inputNames.toTypedArray()

    fun outputNames(): Array<String> = session.outputNames.toTypedArray()

    fun metadataKeys(): Array<String> = session.metadata.customMetadata.keys.toTypedArray()

    fun metadata(key: String): String? = session.metadata.customMetadata[key]

    /** Shape of the output of the last [run]. */
    fun lastShape(): LongArray = shape

    @Synchronized
    fun run(input: ByteArray, inputShape: LongArray): FloatArray {
        val buffer = ByteBuffer.allocateDirect(input.size).order(ByteOrder.nativeOrder())
        buffer.put(input).flip()
        OnnxTensor.createTensor(env, buffer.asFloatBuffer(), inputShape).use { tensor ->
            session.run(mapOf(session.inputNames.first() to tensor)).use { result ->
                val out = result.get(0) as OnnxTensor
                shape = out.info.shape
                val floats = out.floatBuffer
                return FloatArray(floats.remaining()).also { floats.get(it) }
            }
        }
    }
}
