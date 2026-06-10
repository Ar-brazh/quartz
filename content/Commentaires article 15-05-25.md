
There is my commentary for the two first parts : 
Do we keep Ultrafast ultrasound in the title. Even if the scan were done in classical doppler and B-more ? 

Robot pose streamed at 500 hz and recorded Every 0.06 second yes but for calibration only. The US-PET acquisition were made with the probe fixed in position for the whole acquisition 

0.2 mm axial resolution, 0.4 mm latéral résolution where did you get this number ? And how we could see a wire that has 0.2 mm of diameter with a probe that has 0.4 mm latéral résolution ?


You wrote twice "Local comparison" in this paragraph: For visualization and local comparison, PET/CT-derived information was projected onto the native UUS image grid rather than resampling the UUS image into the PET/CT volume. This preserved the UUS image grid and allowed direct local comparison between PET/CT information and the corresponding UUS plane.


I did not do this, it can be done but I need to add a module to the app: "When probe attenuation compensation was required, the segmented 3D probe model described in Section 2.d was inserted into the CT volume used for attenuation correction before PET reconstruction. For robotic acquisitions, the model position was derived from the recorded robot pose and the calibrated transformation chain."


I did not do that either, but it can be done: "Second, PET/CT information was fused with a 3D UUS B-mode acquisition obtained by moving the robot-mounted probe along a controlled trajectory over the vessel axis. This acquisition covered the stenotic region volumetrically and allowed the PET-positive target to be compared with the reconstructed UUS morphology over a larger spatial extent."